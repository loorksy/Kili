from nanobot.market.models import Instrument
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore
from nanobot.trading.instruments import InstrumentMappings, SymbolMapping
from nanobot.trading.proposals import TradePreview, TradeProposal, TradeProposals


async def service_for(tmp_path,client):
    journal = ActionStore(tmp_path / "state.db")
    mappings = InstrumentMappings(RecordStore("mappings",SymbolMapping,journal))
    await mappings.verify_user_mapping(client,Instrument(id="XAU-USD",display_symbol="XAUUSD",asset_class="metal"),"GOLDm")
    return TradeProposals(client,mappings,RecordStore("proposals",TradeProposal,journal),RecordStore("previews",TradePreview,journal))

