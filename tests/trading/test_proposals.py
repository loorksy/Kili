from decimal import Decimal

import pytest

from nanobot.market.models import Instrument
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore
from nanobot.trading.instruments import InstrumentMappings, SymbolMapping
from nanobot.trading.proposals import TradeIntent, TradePreview, TradeProposal, TradeProposals


async def service_for(tmp_path,client):
    journal = ActionStore(tmp_path / "state.db")
    mappings = InstrumentMappings(RecordStore("mappings",SymbolMapping,journal))
    await mappings.verify_user_mapping(client,Instrument(id="XAU-USD",display_symbol="XAUUSD",asset_class="metal"),"GOLDm")
    return TradeProposals(client,mappings,RecordStore("proposals",TradeProposal,journal),RecordStore("previews",TradePreview,journal))


async def test_durable_proposal_preview_and_exact_material_fields(tmp_path,client):
    service = await service_for(tmp_path,client)
    proposal = service.create("websocket:main",TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1")),rationale="Evidence",charts=["chart-reference"])
    preview = await service.preview(proposal.id,proposal.principal)
    material = preview.material_action()
    assert material["account_id"] == "demo" and material["broker_symbol"] == "GOLDm"
    assert material["broker_request"]["volume"] == "0.1"
    assert material["broker_request"]["actionType"] == "ORDER_TYPE_BUY"
    assert service.require_preview(preview.id,proposal.principal).id == preview.id
    restarted = TradeProposals(client,service.mappings,service.proposals,service.previews)
    assert restarted.proposals.get(proposal.id).status == "PREVIEWED"
    newer = await service.preview(proposal.id,proposal.principal)
    with pytest.raises(ValueError,match="replaced"):
        service.require_preview(preview.id,proposal.principal)
    assert newer.effect_key != preview.effect_key
    with pytest.raises(PermissionError):
        service.require_preview(newer.id,"websocket:other")


async def test_volume_step_price_precision_and_mapping_change(tmp_path,client):
    service = await service_for(tmp_path,client)
    for intent in [TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".015")),TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1"),stop_loss=Decimal("2690.123"))]:
        proposal=service.create("websocket:main",intent)
        with pytest.raises(ValueError):
            await service.preview(proposal.id,proposal.principal)
    proposal=service.create("websocket:main",TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1")))
    preview=await service.preview(proposal.id,proposal.principal)
    mapping=service.mappings.require("demo","XAU-USD")
    service.mappings.records.save(mapping)
    with pytest.raises(ValueError,match="mapping changed"):
        service.require_preview(preview.id,proposal.principal)


async def test_close_and_modify_use_verified_exact_target(tmp_path,client):
    service = await service_for(tmp_path,client)
    intent=TradeIntent(canonical_instrument="XAU-USD",operation="close_position",target_id="1")
    proposal=service.create("websocket:main",intent)
    preview=await service.preview(proposal.id,proposal.principal)
    assert preview.broker_request["actionType"] == "POSITION_CLOSE_ID"
    assert preview.broker_request["positionId"] == "1"
    invalid=service.create("websocket:main",intent.model_copy(update={"target_id":"other"}))
    with pytest.raises(ValueError,match="target"):
        await service.preview(invalid.id,invalid.principal)
