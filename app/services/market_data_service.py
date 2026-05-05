import logging
from typing import Optional
from app.db.database import SessionLocal
from app.models.market_data import MarketData

logger = logging.getLogger(__name__)


class MarketDataService:
    """
    Maintains the live market data snapshot for every symbol.

    Updated by the MatchingEngine after each fill.
    Also updates best bid/ask by inspecting the live order book.
    """

    def on_trade(self, symbol, trade_qty, trade_price, bid=0.0, ask=0.0):
        """Call this after every matched fill."""
        session = SessionLocal()
        try:
            md = session.query(MarketData).filter(MarketData.symbol == symbol).first()

            if md is None:
                md = MarketData(
                    symbol     = symbol,
                    open_price = trade_price,
                    high       = trade_price,
                    low        = trade_price,
                )
                session.add(md)

            # VWAP:  new_vwap = (old_vwap * old_vol + price * qty) / new_vol
            new_volume = (md.volume or 0) + trade_qty
            md.vwap       = ((md.vwap or 0.0) * (md.volume or 0) + trade_price * trade_qty) / new_volume
            md.last_price = trade_price
            md.last_qty   = trade_qty
            md.volume     = new_volume
            md.high       = max(md.high or 0.0, trade_price)
            md.low        = min(md.low, trade_price) if (md.low or 0) > 0 else trade_price

            # Update best bid/ask from live book if provided
            if bid > 0:
                md.bid = bid
            if ask > 0:
                md.ask = ask

            session.commit()
            logger.info(f"[MKT] {symbol}: last={trade_price} vol={new_volume} vwap={md.vwap:.4f} hi={md.high} lo={md.low}")
        except Exception as e:
            session.rollback()
            logger.error(f"MarketDataService.on_trade error: {e}")
        finally:
            session.close()

    def update_bbo(self, symbol, bid, ask):
        """Update best bid/offer without a trade (e.g. after cancel/replace)."""
        session = SessionLocal()
        try:
            md = session.query(MarketData).filter(MarketData.symbol == symbol).first()
            if md is None:
                return
            if bid > 0:
                md.bid = bid
            if ask > 0:
                md.ask = ask
            session.commit()
        finally:
            session.close()

    def get_snapshot(self, symbol) -> Optional[MarketData]:
        session = SessionLocal()
        try:
            return session.query(MarketData).filter(MarketData.symbol == symbol).first()
        finally:
            session.close()
