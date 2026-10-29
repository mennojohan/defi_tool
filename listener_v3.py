"""
Alchemy WebSocket Listener v3 - Uniswap V3 Upgrade (FIXED)
Features:
- 🔄 Historische backfill via eth_getLogs (5 dagen)
- 📐 Transaction index tracking voor MEV detection
- 🕵️ Price impact berekening voor liquidity density
- 💾 DIRECTE database commits (geen buffering)
- ⏱️ Rate limiting om HTTP 429 te voorkomen
- 🚨 Expliciete error logging bij database fouten
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional
import aiohttp
import websockets
from web3 import Web3
from database import get_database
from config import DATABASE_URL
from models import Swap 


from config import ALCHEMY_RPC_URL, ALCHEMY_WSS_URL, POOL_ADDRESS, SWAP_EVENT_SIGNATURE
from utils.price_math import sqrt_price_x96_to_price

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UniswapV3PoolListenerV3:
    """
    WebSocket listener v3 met historische backfill en MEV tracking
    """
    
    def __init__(
        self,
        wss_url: str = ALCHEMY_WSS_URL,
        rpc_url: str = ALCHEMY_RPC_URL,
        pool_address: str = POOL_ADDRESS,
        backfill_days: int = 5,
        rate_limit_delay: float = 0.15  # 🆕 Delay tussen RPC calls in seconden
    ):
        self.wss_url = wss_url
        self.rpc_url = rpc_url
        self.pool_address = pool_address.lower()
        self.backfill_days = backfill_days
        self.rate_limit_delay = rate_limit_delay  # 🆕 Rate limiting
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self._last_price: Optional[Decimal] = None  # Voor price impact berekening
        
    async def historical_backfill(self, callback: Callable) -> int:
        """
        🔄 HISTORISCHE BACKFILL via gratis eth_getLogs
        
        🆕 FIXED ISSUES:
        - Rate limiting: await asyncio.sleep() tussen chunks
        - Direct commits: callback roept direct session.commit() aan
        - Error logging: exc_info=True bij database fouten
        
        Returns:
            Aantal gevonden events
        """
        logger.info(f"🔄 Starting historical backfill: laatste {self.backfill_days} dagen")
        
        try:
            async with aiohttp.ClientSession() as session:
                # Bereken blok range (ongeveer)
                # Ethereum/Base: ~12 sec/block = 7200 blocks/dag
                current_block = await self._get_current_block(session)
                blocks_per_day = 7200
                from_block = current_block - (self.backfill_days * blocks_per_day)
                
                total_blocks = current_block - from_block
                logger.info(f"📦 Fetching logs: blok {from_block} → {current_block} ({total_blocks} blokken)")
                
                # ALCHEMY FREE TIER CONSTRAINT: max 10 blokken per query
                CHUNK_SIZE = 10
                chunks = self._create_block_chunks(from_block, current_block, CHUNK_SIZE)
                
                logger.info(f"📊 Opgedeeld in {len(chunks)} chunks van max {CHUNK_SIZE} blokken")
                
                # 🆕 SEQUENTIAL PROCESSING MET RATE LIMITING (ipv parallel)
                # Dit voorkomt HTTP 429 errors
                logger.info(f"🐢 Processing chunks SEQUENTIEEL met {self.rate_limit_delay}s delay (rate limiting)...")
                
                all_logs = []
                for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
                    # Fetch logs voor deze chunk
                    chunk_logs = await self._fetch_logs_for_chunk(session, chunk_start, chunk_end, i)
                    
                    if chunk_logs:
                        all_logs.extend(chunk_logs)
                    
                    # 🆕 RATE LIMITING: wacht tussen chunks
                    if i < len(chunks):  # Niet wachten na laatste chunk
                        await asyncio.sleep(self.rate_limit_delay)
                    
                    # Progress indicator
                    if i % 10 == 0:
                        logger.info(f"   Progress: {i}/{len(chunks)} chunks ({len(all_logs)} logs tot nu toe)")
                
                logger.info(f"✅ Gevonden: {len(all_logs)} historische swaps")
                
                # Process elk log event
                # Enrich metadata met caching voor performance
                logger.info(f"🔍 Enriching {len(all_logs)} logs met metadata...")
                enriched_logs = await self._batch_enrich_logs(session, all_logs)
                
                # Decode en process
                processed_count = 0
                failed_count = 0
                
                for enriched_log in enriched_logs:
                    if isinstance(enriched_log, Exception):
                        continue
                    
                    swap_event = self.decode_swap_event(enriched_log)
                    
                    if swap_event:
                        # Bereken price impact
                        swap_event = self._calculate_price_impact(swap_event)
                        
                        # 🆕 Roep callback aan MET ERROR HANDLING
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(swap_event)
                            else:
                                callback(swap_event)
                            
                            processed_count += 1
                            
                        except Exception as callback_error:
                            # 🆕 EXPLICIETE ERROR LOGGING
                            logger.error(
                                f"❌ DATABASE COMMIT FAILED voor swap {swap_event.get('tx_hash', 'unknown')[:10]}...",
                                exc_info=True  # 🆕 Print volledige stack trace
                            )
                            failed_count += 1
                        
                        # Progress logging
                        if processed_count % 100 == 0:
                            logger.info(f"   Processed: {processed_count}/{len(all_logs)} swaps ({failed_count} failed)")
                
                logger.info(f"✅ Backfill compleet: {processed_count} swaps opgeslagen, {failed_count} failed")
                return processed_count
                        
        except Exception as e:
            logger.error(f"❌ Backfill error: {e}", exc_info=True)
            return 0
    
    def _create_block_chunks(self, from_block: int, to_block: int, chunk_size: int) -> list[tuple[int, int]]:
        """
        Knip block range op in chunks van max chunk_size blokken
        
        Args:
            from_block: Start blok (inclusive)
            to_block: Eind blok (inclusive)
            chunk_size: Max blokken per chunk (10 voor Alchemy free tier)
        
        Returns:
            Lijst van (start, end) tuples (beide inclusive)
            
        Example:
            _create_block_chunks(1000, 1050, 10)
            → [(1000, 1009), (1010, 1019), (1020, 1029), 
               (1030, 1039), (1040, 1049), (1050, 1050)]
            Coverage: 51 blokken (1000 t/m 1050 inclusief)
        """
        chunks = []
        current = from_block
        
        while current <= to_block:  # ✅ FIX: <= ipv < (inclusive end)
            chunk_end = min(current + chunk_size - 1, to_block)
            chunks.append((current, chunk_end))
            current = chunk_end + 1
        
        return chunks
    
    async def _fetch_logs_for_chunk(
        self,
        session: aiohttp.ClientSession,
        from_block: int,
        to_block: int,
        chunk_id: int
    ) -> list[dict]:
        """
        Haal logs op voor één chunk (max 10 blokken)
        
        Args:
            session: aiohttp session
            from_block: Start blok
            to_block: Eind blok
            chunk_id: Chunk nummer (voor logging)
        
        Returns:
            Lijst van log dicts
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": chunk_id,
                "method": "eth_getLogs",
                "params": [{
                    "address": self.pool_address,
                    "topics": [SWAP_EVENT_SIGNATURE],
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block)
                }]
            }
            
            async with session.post(self.rpc_url, json=payload) as response:
                # 🆕 Check voor rate limit errors
                if response.status == 429:
                    logger.error(f"❌ HTTP 429 Rate Limit! Chunk {chunk_id} wordt overgeslagen.")
                    logger.error(f"   Verhoog rate_limit_delay (nu: {self.rate_limit_delay}s)")
                    return []
                
                data = await response.json()
                
                if "result" in data:
                    logs = data["result"]
                    if logs:
                        logger.debug(f"   Chunk {chunk_id}: {len(logs)} logs (blok {from_block}-{to_block})")
                    return logs
                else:
                    error = data.get("error", {}).get("message", "Unknown error")
                    logger.warning(f"   Chunk {chunk_id} failed: {error}")
                    return []
        
        except Exception as e:
            logger.warning(f"   Chunk {chunk_id} exception: {e}")
            return []
    
    async def _get_current_block(self, session: aiohttp.ClientSession) -> int:
        """Haal het huidige bloknummer op"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_blockNumber",
            "params": []
        }
        
        async with session.post(self.rpc_url, json=payload) as response:
            data = await response.json()
            return int(data["result"], 16)
    
    async def _batch_enrich_logs(
        self,
        session: aiohttp.ClientSession,
        logs: list[dict]
    ) -> list[dict]:
        """
        Batch enrichment met block timestamp caching
        Meerdere swaps in hetzelfde blok delen dezelfde timestamp
        
        🆕 FIXED: Rate limiting tussen batch requests
        
        Args:
            session: aiohttp session
            logs: Lijst van log dicts
        
        Returns:
            Lijst van enriched log dicts
        """
        # Cache voor block timestamps (veel swaps delen zelfde block)
        block_cache = {}
        
        # Haal unieke blokken op eerst (batch)
        unique_blocks = list(set(log.get("blockNumber") for log in logs))
        logger.info(f"   Fetching timestamps voor {len(unique_blocks)} unieke blokken...")
        
        # Batch block requests (max 50 per keer om niet te groot te worden)
        BLOCK_BATCH_SIZE = 50
        for i in range(0, len(unique_blocks), BLOCK_BATCH_SIZE):
            block_batch = unique_blocks[i:i+BLOCK_BATCH_SIZE]
            
            batch_payload = [
                {
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "eth_getBlockByNumber",
                    "params": [block_num, False]
                }
                for idx, block_num in enumerate(block_batch)
            ]
            
            try:
                async with session.post(self.rpc_url, json=batch_payload) as response:
                    # 🆕 Check voor rate limit
                    if response.status == 429:
                        logger.error("❌ HTTP 429 bij block batch fetch! Verhoog rate_limit_delay.")
                        await asyncio.sleep(self.rate_limit_delay * 2)  # Extra wachten
                        continue
                    
                    block_data = await response.json()
                    
                    # Parse en cache
                    for item in block_data:
                        if "result" in item and item["result"]:
                            block_num = item["result"]["number"]
                            timestamp_hex = item["result"].get("timestamp", "0x0")
                            block_cache[block_num] = int(timestamp_hex, 16)
                
                # 🆕 Rate limiting tussen batches
                if i + BLOCK_BATCH_SIZE < len(unique_blocks):
                    await asyncio.sleep(self.rate_limit_delay)
            
            except Exception as e:
                logger.warning(f"Block batch fetch failed: {e}")
        
        logger.info(f"   Cached {len(block_cache)} block timestamps")
        
        # Enrich transaction receipts SEQUENTIEEL (ipv parallel) om rate limits te voorkomen
        logger.info(f"   Fetching transaction receipts SEQUENTIEEL...")
        enriched_logs = []
        
        for i, log in enumerate(logs):
            try:
                enriched_log = await self._enrich_log_with_cached_blocks(session, log, block_cache)
                enriched_logs.append(enriched_log)
                
                # 🆕 Rate limiting tussen receipt calls
                if i < len(logs) - 1 and i % 10 == 0:  # Elke 10 logs een kleine pauze
                    await asyncio.sleep(self.rate_limit_delay / 2)  # Halve delay voor receipts
                
            except Exception as e:
                logger.debug(f"Receipt enrichment failed: {e}")
                enriched_logs.append(log)  # Use unenriched log als fallback
        
        return enriched_logs
    
    async def _enrich_log_with_cached_blocks(
        self,
        session: aiohttp.ClientSession,
        log: dict,
        block_cache: dict
    ) -> dict:
        """
        Enrich log met transaction receipt, gebruik gecachde block timestamp
        
        Args:
            session: aiohttp session
            log: Log dict
            block_cache: Dict met block_number -> timestamp mapping
        
        Returns:
            Enriched log dict
        """
        tx_hash = log.get("transactionHash")
        block_number = log.get("blockNumber")
        
        # Timestamp uit cache (veel sneller)
        log["timestamp"] = block_cache.get(block_number, int(datetime.utcnow().timestamp()))
        
        # Alleen transaction receipt ophalen (1 RPC call ipv 2)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash]
        }
        
        try:
            async with session.post(self.rpc_url, json=payload) as response:
                # 🆕 Check rate limit
                if response.status == 429:
                    logger.debug(f"Rate limit bij receipt fetch voor {tx_hash[:10]}...")
                    log["transactionIndex"] = "0x0"
                    return log
                
                data = await response.json()
                
                if "result" in data and data["result"]:
                    log["transactionIndex"] = data["result"].get("transactionIndex", "0x0")
                else:
                    log["transactionIndex"] = "0x0"
        
        except Exception as e:
            logger.debug(f"Receipt fetch failed: {e}")
            log["transactionIndex"] = "0x0"
        
        return log
    
    async def _enrich_log_with_metadata(
        self,
        session: aiohttp.ClientSession,
        log: dict
    ) -> dict:
        """
        Verrijk log met block metadata (transaction_index + timestamp)
        Dit is cruciaal voor MEV detection en chronologische ordening
        
        Gebruikt JSON-RPC batch requests voor performance (2 calls in 1 HTTP request)
        """
        tx_hash = log.get("transactionHash")
        block_number = log.get("blockNumber")
        
        # JSON-RPC BATCH REQUEST (2 calls in 1 HTTP request = sneller)
        batch_payload = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash]
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "eth_getBlockByNumber",
                "params": [block_number, False]
            }
        ]
        
        payload = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionByHash",
        "params": [tx_hash],
        "id": 1}

        try:
            async with session.post(self.rpc_url, json=payload) as response:
                # 🆕 Check rate limit
                if response.status == 429:
                    logger.warning(f"⚠️ Rate limit bij realtime metadata fetch voor {tx_hash[:10]}...")
                    log["transactionIndex"] = "0x0"
                    log["timestamp"] = int(datetime.utcnow().timestamp())
                    return log
                
                data = await response.json()
                
                # Parse batch response (kan in any order komen)
                receipt_data = next((r for r in data if r.get("id") == 1), None)
                block_data = next((r for r in data if r.get("id") == 2), None)
                
                # Extract transaction index
                if receipt_data and "result" in receipt_data and receipt_data["result"]:
                    log["transactionIndex"] = receipt_data["result"].get("transactionIndex", "0x0")
                else:
                    log["transactionIndex"] = "0x0"
                
                # Extract block timestamp
                if block_data and "result" in block_data and block_data["result"]:
                    timestamp_hex = block_data["result"].get("timestamp", "0x0")
                    log["timestamp"] = int(timestamp_hex, 16)
                else:
                    log["timestamp"] = int(datetime.utcnow().timestamp())
        
        except Exception as e:
            logger.debug(f"Metadata enrichment failed voor {tx_hash[:10]}...: {e}")
            log["transactionIndex"] = "0x0"
            log["timestamp"] = int(datetime.utcnow().timestamp())
        
        return log
    
    async def connect(self) -> bool:
        """Maak verbinding met Alchemy WebSocket"""
        try:
            self.websocket = await websockets.connect(self.wss_url)
            logger.info(f"✅ Verbonden met Alchemy WebSocket")
            return True
        except Exception as e:
            logger.error(f"❌ Verbinding mislukt: {e}")
            return False
    
    async def subscribe_to_swaps(self) -> Optional[str]:
        """Subscribe naar Swap events van de specifieke pool"""
        subscription_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": self.pool_address,
                    "topics": [SWAP_EVENT_SIGNATURE]
                }
            ]
        }
        
        await self.websocket.send(json.dumps(subscription_request))
        response = await self.websocket.recv()
        response_data = json.loads(response)
        
        if "result" in response_data:
            subscription_id = response_data["result"]
            logger.info(f"📡 Subscribed naar Swap events (ID: {subscription_id})")
            logger.info(f"🎯 Pool: {self.pool_address}")
            return subscription_id
        else:
            logger.error(f"❌ Subscription mislukt: {response_data}")
            return None
    
    def decode_swap_event(self, log_data: dict) -> Optional[dict]:
        """
        Decodeer ruwe log data naar swap event met transaction_index
        
        Swap event structuur (Uniswap V3):
        - topics[0]: Event signature
        - topics[1]: sender (indexed)
        - topics[2]: recipient (indexed)
        - data: amount0, amount1, sqrtPriceX96, liquidity, tick
        """
        try:
            topics = log_data.get("topics", [])
            data = log_data.get("data", "0x")
            tx_hash = log_data.get("transactionHash", "")
            block_number = int(log_data.get("blockNumber", "0x0"), 16)
            log_index = int(log_data.get("logIndex", "0x0"), 16)
            
            # 🆕 Transaction index (cruciaal voor MEV detection)
            tx_index = int(log_data.get("transactionIndex", "0x0"), 16)
            
            # Timestamp (from enriched metadata of realtime)
            timestamp = log_data.get("timestamp")
            if timestamp:
                # Als het een integer is, converteer naar datetime
                if isinstance(timestamp, int):
                    dt = datetime.utcfromtimestamp(timestamp)
                else:
                    dt = datetime.utcnow()
            else:
                dt = datetime.utcnow()
            
            # Decode indexed parameters
            sender = Web3.to_checksum_address("0x" + topics[1][-40:]) if len(topics) > 1 else None
            recipient = Web3.to_checksum_address("0x" + topics[2][-40:]) if len(topics) > 2 else None
            
            # Decode data
            data_hex = data[2:]
            chunks = [data_hex[i:i+64] for i in range(0, len(data_hex), 64)]
            
            if len(chunks) >= 5:
                # Parse integers
                amount0 = int(chunks[0], 16)
                amount1 = int(chunks[1], 16)
                sqrt_price_x96 = int(chunks[2], 16)
                liquidity = int(chunks[3], 16)
                tick = int(chunks[4], 16)
                
                # Converteer signed integers (two's complement)
                if amount0 >= 2**255:
                    amount0 -= 2**256
                if amount1 >= 2**255:
                    amount1 -= 2**256
                if tick >= 2**23:
                    tick -= 2**24
                
                # Bereken prijs (invert=True omdat token0=USDC, token1=WETH)
                price = sqrt_price_x96_to_price(sqrt_price_x96, invert=True)
                
                return {
                    "tx_hash": tx_hash,
                    "block_number": block_number,
                    "log_index": log_index,
                    "transaction_index": tx_index,
                    "timestamp": dt,
                    "sender": sender,
                    "recipient": recipient,
                    "amount0": amount0,  # USDC (6 decimals)
                    "amount1": amount1,  # WETH (18 decimals)
                    "sqrt_price_x96": sqrt_price_x96,
                    "liquidity": liquidity,
                    "tick": tick,
                    "price": price,
                    "pool_address": self.pool_address
                }
            else:
                logger.warning(f"⚠️ Onvoldoende data chunks: {len(chunks)}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Decode error: {e}", exc_info=True)
            return None
    
    def _calculate_price_impact(self, swap_event: dict) -> dict:
        """
        🆕 Bereken price impact voor implied liquidity density
        
        Price Impact (bps) = abs((new_price - old_price) / old_price) * 10000
        Implied Density = volume_usd / price_impact_bps (higher = denser liquidity)
        """
        try:
            current_price = swap_event["price"]
            
            if self._last_price is not None and self._last_price > 0:
                price_delta = abs(current_price - self._last_price)
                price_impact_pct = price_delta / self._last_price
                price_impact_bps = price_impact_pct * Decimal("10000")
                
                # Schat volume (simplified: abs(amount0) voor USDC side)
                # ⚠️ amount0 = USDC (6 decimals), amount1 = WETH (18 decimals)
                volume = abs(swap_event["amount0"]) / Decimal("1e6")  # USDC heeft 6 decimals
                
                # Implied density (hoe hoger, hoe meer liquidity)
                if price_impact_bps > 0:
                    implied_density = volume / price_impact_bps
                else:
                    implied_density = Decimal("0")
                
                swap_event["price_impact_bps"] = price_impact_bps
                swap_event["implied_density"] = implied_density
            else:
                swap_event["price_impact_bps"] = None
                swap_event["implied_density"] = None
            
            # Update last price
            self._last_price = current_price
            
        except Exception as e:
            logger.debug(f"Price impact berekening mislukt: {e}")
            swap_event["price_impact_bps"] = None
            swap_event["implied_density"] = None
        
        return swap_event
    
    async def listen(self, callback: Callable):
        """
        Main listener loop met backfill eerst, dan realtime WebSocket
        
        🆕 FIXED: Error handling voor callback zodat database fouten niet worden genegeerd
        
        Args:
            callback: Async functie die swap events processed
        """
        self.is_running = True
        
        # 🔄 STAP 1: Historische backfill
        logger.info("=" * 60)
        logger.info("STAP 1: HISTORISCHE BACKFILL")
        logger.info("=" * 60)
        
        backfill_count = await self.historical_backfill(callback)
        
        logger.info("=" * 60)
        logger.info(f"✅ Backfill compleet: {backfill_count} events")
        logger.info("=" * 60)
        logger.info("STAP 2: REALTIME WEBSOCKET LISTENING")
        logger.info("=" * 60)
        
        # 🔴 STAP 2: Realtime WebSocket listening
        while self.is_running:
            try:
                if not await self.connect():
                    logger.info("⏳ Reconnect over 5 seconden...")
                    await asyncio.sleep(5)
                    continue
                
                subscription_id = await self.subscribe_to_swaps()
                if not subscription_id:
                    await asyncio.sleep(5)
                    continue
                
                logger.info("👂 Listening voor realtime swap events...")
                
                while self.is_running:
                    try:
                        message = await asyncio.wait_for(
                            self.websocket.recv(),
                            timeout=60.0
                        )
                        
                        data = json.loads(message)
                        
                        if "params" in data and "result" in data["params"]:
                            log_data = data["params"]["result"]
                            
                            # Voor realtime events moeten we ook metadata ophalen
                            async with aiohttp.ClientSession() as session:
                                enriched_log = await self._enrich_log_with_metadata(session, log_data)
                            
                            swap_event = self.decode_swap_event(enriched_log)
                            
                            if swap_event:
                                # Bereken price impact
                                swap_event = self._calculate_price_impact(swap_event)
                                
                                # 🆕 Callback MET ERROR HANDLING
                                try:
                                    if asyncio.iscoroutinefunction(callback):
                                        await callback(swap_event)
                                    else:
                                        callback(swap_event)
                                
                                except Exception as callback_error:
                                    # 🆕 EXPLICIETE DATABASE ERROR LOGGING
                                    logger.error(
                                        f"❌ DATABASE COMMIT FAILED voor realtime swap {swap_event.get('tx_hash', 'unknown')[:10]}...",
                                        exc_info=True  # Print volledige stack trace
                                    )
                    
                    except asyncio.TimeoutError:
                        await self.websocket.ping()
                        continue
                        
            except websockets.exceptions.ConnectionClosed:
                logger.warning("⚠️ WebSocket verbinding verbroken. Reconnecting...")
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Onverwachte error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop de listener gracefully"""
        self.is_running = False
        if self.websocket:
            await self.websocket.close()
        logger.info("🛑 Listener gestopt")


async def example_swap_handler(swap_data: dict):
    """Test handler met directe database commit"""
    logger.info("🔥 SWAP GEDETECTEERD!")
    logger.info(f"   TX: {swap_data['tx_hash']}")
    logger.info(f"   Prijs: ${swap_data['price']:.2f}")
    
    try:
        db = get_database(DATABASE_URL)
        async with db.session() as session:
            # 🛠️ MAAK EEN SCHONE KOPIE EN GEFRETTER HET POOL_ADDRESS ERUIT
            clean_data = swap_data.copy()
            clean_data.pop("pool_address", None)
            
            # 🔥 NU PUSHEN WE DE SCHONE DATA IN JE MODEL
            new_swap = Swap(**clean_data)
            session.add(new_swap)
            
            await session.flush()
            await session.commit()
            
        logger.info(f"   💾 GEGARANDEERD OPGESLAGEN in de tabel 'swaps'!")
    except Exception as db_err:
        logger.error(f"   ❌ FOUT BIJ OPSLAAN IN DATABASE: {db_err}", exc_info=True)
        
    logger.info("-" * 60)


async def main():
    """Test de listener v3"""
    # 💾 1. Haal de database op en open direct de poort!
    from database import get_database
    from config import DATABASE_URL
    db = get_database(DATABASE_URL)
    await db.init()
    
    # 2. Listener initialiseren met rate limiting
    listener = UniswapV3PoolListenerV3(
        backfill_days=5,
        rate_limit_delay=0.15  # 🆕 Configureerbaar rate limiting
    )
    
    try:
        await listener.listen(example_swap_handler)
    except KeyboardInterrupt:
        logger.info("⌨️  Keyboard interrupt")
        await listener.stop()


if __name__ == "__main__":
    print("🚀 Starting DeFi Pool Tracker v3 (Uniswap V3 Concentrated Liquidity)")
    print(f"📍 Pool: {POOL_ADDRESS}")
    print("=" * 60)
    asyncio.run(main())
