"""Local mission execution evidence. This adapter never calls a broker mutation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import Field

from nanobot.security.actions import Effect
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.metaapi import BrokerDeal, BrokerItem, TradeResponse
from nanobot.trading.mission_models import AccountObservation, TradingMandate
from nanobot.trading.missions import TradingMissions
from nanobot.trading.proposals import TradePreview
from nanobot.trading.risk import side_of


class SimulationBook(RuntimeRecord):
    positions: list[BrokerItem] = Field(default_factory=list,max_length=100)
    orders: list[BrokerItem] = Field(default_factory=list,max_length=100)
    order_history: list[BrokerItem] = Field(default_factory=list,max_length=10000)
    deals: list[BrokerDeal] = Field(default_factory=list,max_length=10000)
    receipts: dict[str,TradeResponse] = Field(default_factory=dict,max_length=10000)


class MissionSimulation:
    def __init__(self, service: TradingMissions, mandate: TradingMandate):
        self.service,self.mandate = service,mandate
        self.records = RecordStore("mission_simulation",SimulationBook,service.journal)

    def get(self) -> SimulationBook:
        try:
            return self.records.get(self.mandate.id)
        except ValueError:
            return self.records.create(SimulationBook(id=self.mandate.id))

    async def pnl(self, position: BrokerItem, volume: Decimal | None = None) -> Decimal:
        spec = await self.service.client.specification(position.symbol)
        price = await self.service.client.price(position.symbol)
        if spec.contract_size is None or spec.currency_profit != self.mandate.envelope.currency or position.open_price is None or position.volume is None:
            raise ValueError("Simulation needs direct account-currency contract information")
        distance = price.bid-position.open_price if side_of(position) == "buy" else position.open_price-price.ask
        return distance*spec.contract_size*(volume if volume is not None else position.volume)

    async def close(self, book: SimulationBook, position: BrokerItem, volume: Decimal | None = None) -> None:
        assert position.volume is not None
        amount = volume or position.volume
        book.deals.append(BrokerDeal(id=f"sim-deal-{len(book.deals)}",positionId=position.id,clientId=position.client_id,
            type="DEAL_TYPE_SELL" if side_of(position) == "buy" else "DEAL_TYPE_BUY",entryType="DEAL_ENTRY_OUT",
            profit=await self.pnl(position,amount),time=datetime.now(timezone.utc).isoformat()))
        if amount == position.volume:
            book.positions.remove(position)
        else:
            position.volume -= amount

    async def execute(self, preview: TradePreview, effect: Effect) -> TradeResponse:
        book = self.get()
        if effect.id in book.receipts:
            return book.receipts[effect.id]
        intent = preview.intent
        target = next((p for p in [*book.positions,*book.orders] if p.id == intent.target_id),None)
        identity = "sim-"+effect.id
        if intent.operation == "open":
            entry = intent.price or (preview.broker_price.ask if intent.side == "buy" else preview.broker_price.bid)
            item = BrokerItem(id=identity,symbol=preview.broker_symbol,type="POSITION_TYPE_"+intent.side.upper(),
                volume=intent.volume,clientId=str(preview.broker_request["clientId"]),openPrice=entry,
                stopLoss=intent.stop_loss,takeProfit=intent.take_profit,profit=Decimal(0),expirationTime=intent.expiration_time)
            if intent.order_type != "market":
                item.type = "ORDER_TYPE_"+intent.side.upper()+"_"+intent.order_type.upper()
                book.orders.append(item)
            else:
                book.positions.append(item)
            response = TradeResponse(stringCode="TRADE_RETCODE_PLACED" if intent.order_type != "market" else "TRADE_RETCODE_DONE",
                orderId=identity,positionId=identity if intent.order_type == "market" else None)
        else:
            if target is None:
                raise ValueError("Simulation cannot mutate a real/manual broker target")
            if intent.operation == "close_position":
                await self.close(book,target,intent.volume)
            elif intent.operation == "cancel_order":
                book.order_history.append(target.model_copy(update={"state":"ORDER_STATE_CANCELED"}))
                book.orders.remove(target)
            else:
                if intent.stop_loss is not None:
                    target.stop_loss = intent.stop_loss
                if intent.take_profit is not None:
                    target.take_profit = intent.take_profit
                if intent.price is not None:
                    target.open_price = intent.price
                if intent.volume is not None:
                    target.volume = intent.volume
            response = TradeResponse(stringCode="TRADE_RETCODE_DONE",positionId=target.id)
        book.receipts[effect.id] = response
        self.records.save(book)
        return response

    async def observe(self, observation: AccountObservation) -> tuple[AccountObservation,list[BrokerDeal]]:
        book = self.get()
        for order in list(book.orders):
            if order.expiration_time and datetime.fromisoformat(order.expiration_time.replace("Z","+00:00")) <= datetime.now(timezone.utc):
                book.order_history.append(order.model_copy(update={"state":"ORDER_STATE_EXPIRED"}))
                book.orders.remove(order)
                continue
            price = await self.service.client.price(order.symbol)
            if order.open_price is None:
                raise ValueError("Simulation pending entry has no price")
            side = side_of(order)
            quote = price.ask if side == "buy" else price.bid
            hit = quote <= order.open_price if side == "buy" and order.type.endswith("LIMIT") or side == "sell" and order.type.endswith("STOP") else quote >= order.open_price
            if hit:
                book.order_history.append(order.model_copy(update={"state":"ORDER_STATE_FILLED"}))
                book.orders.remove(order)
                order.type = "POSITION_TYPE_"+side.upper()
                order.open_price = quote
                book.positions.append(order)
        for position in list(book.positions):
            position.profit = await self.pnl(position)
            price = await self.service.client.price(position.symbol)
            quote = price.bid if side_of(position) == "buy" else price.ask
            stopped = position.stop_loss is not None and (quote <= position.stop_loss if side_of(position) == "buy" else quote >= position.stop_loss)
            targeted = position.take_profit is not None and (quote >= position.take_profit if side_of(position) == "buy" else quote <= position.take_profit)
            if stopped or targeted:
                await self.close(book,position)
        book = self.records.save(book)
        realized = sum((d.profit+d.swap+d.commission for d in book.deals),Decimal(0))
        unrealized = sum((p.profit or Decimal(0) for p in book.positions),Decimal(0))
        margin = Decimal(0)
        for item in [*book.positions,*book.orders]:
            if item.volume is None or item.open_price is None:
                raise ValueError("Simulation exposure cannot estimate margin")
            margin += await self.service.client.calculate_margin(item.symbol,side_of(item),item.volume,item.open_price)
        observation.account.balance += realized
        observation.account.equity += realized+unrealized
        observation.account.margin += margin
        observation.account.free_margin = observation.account.equity-observation.account.margin
        observation.positions.extend(book.positions)
        observation.orders.extend(book.orders)
        return observation,book.deals
