# Fake versions of the LLM and the MCP tools, shared by the agent tests.
#
# The agents normally call a real model and real MCP servers. In tests we
# replace them with these fakes, so we decide exactly what they "answer"
# and can check what the agent does with it.

import json


class FakeMessage:
    """Stands in for the message a real model returns. The agents only read .content."""

    def __init__(self, content):
        self.content = content


class FakeLLM:
    """A pretend model.

    answers: what it replies, in order. One string per call.
    If an answer is an Exception, the call raises it instead, which is how
    we test what happens when the model fails.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []          # every prompt it received, so tests can inspect them

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)   # the last message is the user prompt
        answer = self.answers.pop(0)

        if isinstance(answer, Exception):
            raise answer

        return FakeMessage(answer)


def mcp_text(data):
    """Wraps data the way an MCP tool result arrives: a list with one text block."""
    if not isinstance(data, str):
        data = json.dumps(data)
    return [{"type": "text", "text": data}]


def fake_tool(result, calls=None):
    """Builds a fake async MCP tool function that always returns `result`.

    If `result` is an Exception, the tool raises it instead.
    If a `calls` list is given, every call's arguments are added to it.
    """

    async def tool(*args):
        if calls is not None:
            calls.append(args)

        if isinstance(result, Exception):
            raise result

        return result

    return tool