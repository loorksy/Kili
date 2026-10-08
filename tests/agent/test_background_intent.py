import pytest

from nanobot.agent.goal_permission import GoalInputScope, goal_mutation_allowed, persistent_request
from nanobot.bus.events import InboundMessage


@pytest.mark.parametrize("text", ["Monitor gold this week", "Tell me when the report finishes", "Send me a report at 20:00", "راقب الذهب هذا الأسبوع"])
def test_explicit_background_intent_is_current_user_permission_only(text):
    assert persistent_request(text)
    with GoalInputScope(InboundMessage(channel="websocket", sender_id="user", chat_id="main", content=text)):
        assert goal_mutation_allowed()
    assert not goal_mutation_allowed()
    with GoalInputScope(InboundMessage(channel="system", sender_id="subagent", chat_id="main", content=text)):
        assert not goal_mutation_allowed()


def test_normal_chat_does_not_authorize_background_goal():
    with GoalInputScope(InboundMessage(channel="websocket", sender_id="user", chat_id="main", content="Analyze gold")):
        assert not goal_mutation_allowed()
