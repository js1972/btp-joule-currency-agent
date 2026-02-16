# Joule A2A: Connect Code-Based Agents into the Joule Ecosystem

Many organizations began early by building their own AI agents and assistants, often with frameworks such as LangChain and LangGraph. This guide shows how a custom implementation can be connected to Joule by combining pro-code extensibility with A2A.

For demonstration, a minimal ReAct agent written in Python with LangGraph is used.

## Background

The A2A protocol is an open standard designed to normalize how agents collaborate across vendors and stacks. It specifies how agents expose capabilities, how tasks are exchanged, how lifecycle events are handled, and how discovery works via Agent Cards. Communication is typically implemented with transports such as HTTP and JSON-RPC, while the internal logic of each agent remains private.

Many practitioners already worked with Joule Studio as the low-code approach for extending Joule. Pro-code extensibility broadens the reachable scenarios. It enables deeper logic, nested structures, richer response control, and remote agent invocation via A2A.

In the pro-code model, developers create **capabilities**. A capability groups the skills Joule may call for a user request. Two artifacts are essential: **scenarios** and **functions**.

A scenario is the entry definition. It contains a name, description, and optional parameters. Joule evaluates this information during skill selection. The scenario points to the function that should run.

A function contains executable logic. It is composed of actions such as calling APIs, shaping messages, or invoking another agent.

These artifacts are created as YAML projects and deployed to a Joule instance. Two tools support this: the Joule Studio extension for Visual Studio Code and the Joule Studio CLI. The flow below relies on the CLI.

High-level steps:

1. Install the CLI.
2. Collect authentication details for a Joule instance.
3. Log in with `joule login`.
4. Compile and deploy the capability into a bot.

Joule uses **bots** as isolated environments with their own URLs. The default tenant bot is typically `sap_digital_assistant`.

---

## 1. Building the AI Agent

The first task is implementing an agent and exposing it through an A2A server. Sample material from the A2A project is used as the base.

LangGraph is chosen because it is widely adopted, but any framework or language is acceptable. A2A defines the endpoint structure and schemas, not the internal runtime. In this example, Python is deployed on SAP Cloud Foundry.

### Project structure

```text
app/
├── agent.py
├── agent_executor.py
├── app.py
├── manifest.yaml
├── requirements.txt
├── runtime.txt
└── test_client.py
```

### agent.py

```python
import os

from collections.abc import AsyncIterable
from typing import Any, Literal

import httpx

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from gen_ai_hub.proxy.langchain.openai import ChatOpenAI
from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

proxy_client = get_proxy_client('gen-ai-hub')

memory = MemorySaver()

@tool
def get_exchange_rate(
    currency_from: str = 'USD',
    currency_to: str = 'EUR',
    currency_date: str = 'latest',
):
    """Use this to get current exchange rate."""
    try:
        response = httpx.get(
            f'https://api.frankfurter.app/{currency_date}',
            params={'from': currency_from, 'to': currency_to},
        )
        response.raise_for_status()

        data = response.json()
        if 'rates' not in data:
            return {'error': 'Invalid API response format.'}
        return data
    except httpx.HTTPError as e:
        return {'error': f'API request failed: {e}'}
    except ValueError:
        return {'error': 'Invalid JSON response from API.'}


class ResponseFormat(BaseModel):
    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str


class CurrencyAgent:
    """CurrencyAgent - a specialized assistant for currency conversions."""

    SYSTEM_INSTRUCTION = (
        'You are a specialized assistant for currency conversions. '
        "Your sole purpose is to use the 'get_exchange_rate' tool to answer questions about currency exchange rates. "
        'If the user asks about anything other than currency conversion or exchange rates, '
        'politely state that you cannot help with that topic and can only assist with currency-related queries. '
        'Do not attempt to answer unrelated questions or use tools for other purposes.'
    )

    FORMAT_INSTRUCTION = (
        'Set response status to input_required if the user needs to provide more information to complete the request.'
        'Set response status to error if there is an error while processing the request.'
        'Set response status to completed if the request is complete.'
    )

    def __init__(self):
        self.model = ChatOpenAI(
            proxy_model_name='gpt-4o-mini',
            proxy_client=proxy_client,
            temperature=0
        )
        self.tools = [get_exchange_rate]

        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=(self.FORMAT_INSTRUCTION, ResponseFormat),
        )

    async def stream(self, query, context_id) -> AsyncIterable[dict[str, Any]]:
        inputs = {'messages': [('user', query)]}
        config = {'configurable': {'thread_id': context_id}}

        for item in self.graph.stream(inputs, config, stream_mode='values'):
            message = item['messages'][-1]
            if (
                isinstance(message, AIMessage)
                and message.tool_calls
                and len(message.tool_calls) > 0
            ):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Looking up the exchange rates...',
                }
            elif isinstance(message, ToolMessage):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Processing the exchange rates..',
                }

        yield self.get_agent_response(config)

    def get_agent_response(self, config):
        current_state = self.graph.get_state(config)
        structured_response = current_state.values.get('structured_response')
        if structured_response and isinstance(
            structured_response, ResponseFormat
        ):
            if structured_response.status == 'input_required':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            if structured_response.status == 'error':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            if structured_response.status == 'completed':
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': structured_response.message,
                }

        return {
            'is_task_complete': False,
            'require_user_input': True,
            'content': (
                'We are unable to process your request at the moment. '
                'Please try again.'
            ),
        }

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']
```

The implementation is a typical ReAct agent. The only adaptation for A2A is the normalized stream output, which the executor converts into task state updates.

### agent_executor.py

```python
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError

from agent import CurrencyAgent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CurrencyAgentExecutor(AgentExecutor):
    """Currency Conversion AgentExecutor Example."""

    def __init__(self):
        self.agent = CurrencyAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        query = context.get_user_input()
        task = context.current_task

        if not task:
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        logger.info(f"Context properties: {vars(context)}")
        logger.info(f"Task properties: {vars(task)}")

        try:
            async for item in self.agent.stream(query, task.context_id):
                is_task_complete = item['is_task_complete']
                require_user_input = item['require_user_input']

                if not is_task_complete and not require_user_input:
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(
                            item['content'],
                            task.context_id,
                            task.id,
                        ),
                    )
                elif require_user_input:
                    await updater.update_status(
                        TaskState.input_required,
                        new_agent_text_message(
                            item['content'],
                            task.context_id,
                            task.id,
                        ),
                        final=True,
                    )
                    break
                else:
                    await updater.add_artifact(
                        [Part(root=TextPart(text=item['content']))],
                        name='conversion_result',
                    )
                    await updater.complete()
                    break

        except Exception as e:
            logger.error(f'An error occurred while streaming the response: {e}')
            raise ServerError(error=InternalError()) from e

    def _validate_request(self, context: RequestContext) -> bool:
        return False

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise ServerError(error=UnsupportedOperationError())
```

The executor is the protocol adapter. It translates between A2A task mechanics and the agent’s streaming interface.

### app.py

```python
import logging
import os

import httpx

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from dotenv import load_dotenv

from agent import CurrencyAgent
from agent_executor import CurrencyAgentExecutor


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 10000))

capabilities = AgentCapabilities(streaming=True, push_notifications=True)
skill = AgentSkill(
    id='convert_currency',
    name='Currency Exchange Rates Tool',
    description='Helps with exchange values between various currencies',
    tags=['currency conversion', 'currency exchange'],
    examples=['What is exchange rate between USD and GBP?'],
)
agent_card = AgentCard(
    name='Currency Agent',
    description='Helps with exchange rates for currencies',
    url=f'https://my-python-agent.cfapps.sap.hana.ondemand.com',
    version='1.0.0',
    default_input_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    default_output_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    capabilities=capabilities,
    skills=[skill],
)

httpx_client = httpx.AsyncClient()
push_config_store = InMemoryPushNotificationConfigStore()
push_sender = BasePushNotificationSender(
    httpx_client=httpx_client,
    config_store=push_config_store
)
request_handler = DefaultRequestHandler(
    agent_executor=CurrencyAgentExecutor(),
    task_store=InMemoryTaskStore(),
    push_config_store=push_config_store,
    push_sender=push_sender
)
server = A2AStarletteApplication(
    agent_card=agent_card, http_handler=request_handler
)

app = server.build()


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
```

### manifest.yaml

```yaml
applications:
  - name: currency-agent
    memory: 512M
    disk_quota: 1G

    buildpacks:
      - python_buildpack

    env:
      AICORE_AUTH_URL: "<your-auth-url>"
      AICORE_CLIENT_ID: "<your-client-id>"
      AICORE_CLIENT_SECRET: "<your-client-secret>"
      AICORE_RESOURCE_GROUP: "<your-resource-group>"
      AICORE_BASE_URL: "<your-base-url>"

    command: uvicorn app:app --host 0.0.0.0 --port ${PORT}
```

### runtime.txt

```text
python-3.13.9
```

---

## 2. Building the Joule Pro-Code Capability

```text
currency_agent_capability/
├── functions/
│   └── currency_agent_function.yaml
├── scenarios/
│   └── currency_agent_scenario.yaml
└── capability.sapdas.yaml
```

### capability.sapdas.yaml

```yaml
schema_version: 3.27.0

metadata:
  namespace: joule.ext
  name: currency_agent_capability
  version: 1.0.0
  display_name: Currency Agent Capability
  description: Capability containing the currency agent

system_aliases:
  CURRENCY_AGENT:
    destination: CURRENCY_AGENT
```

### currency_agent_scenario.yaml

```yaml
description: The Currency Agent supports converting between different currencies.
target:
  name: currency_agent_function
  type: function
```

### currency_agent_function.yaml

```yaml
action_groups:
  - actions:
      - type: agent-request
        system_alias: CURRENCY_AGENT
        agent_type: remote
        result_variable: "apiResponse"
      - type: message
        message:
          type: text
          content: Function <? apiResponse ?> has been triggered
```

---

## 3. Destination Creation

Create a destination in BTP that points to the URL of the deployed A2A server. The name must match the system alias.

---

## 4. Deploy the Capability

Package and deploy via the CLI. After activation, Joule can route requests to the remote service.

---

## Result

A user request triggers the scenario, which calls the function. The function invokes the external agent through A2A. The response flows back into Joule while orchestration remains within the platform.

Additional topics worth examining include principal propagation, cross-turn context persistence, and advanced response modeling.
