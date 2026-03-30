import logging
import os
import json

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
from auth import wrap_with_ias_auth
from logging_utils import configure_logging


load_dotenv()

configure_logging()
logger = logging.getLogger(__name__)


# Get host and port from environment variables (Cloud Foundry sets PORT)
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 10000))


def get_public_url() -> str:
    # Prefer an explicit override so deployments can advertise an App Router,
    # API Management endpoint, or custom domain instead of the raw CF route.
    configured_url = os.getenv('AGENT_PUBLIC_URL')
    if configured_url:
        return configured_url.rstrip('/')

    # In direct Cloud Foundry deployments, use the first mapped public route.
    vcap_application = os.getenv('VCAP_APPLICATION')
    if vcap_application:
        try:
            app_info = json.loads(vcap_application)
        except json.JSONDecodeError:
            logger.warning(
                'VCAP_APPLICATION is present but could not be parsed. Falling back '
                'to local HOST/PORT.'
            )
        else:
            uris = app_info.get('application_uris') or app_info.get('uris') or []
            if uris:
                return f"https://{uris[0].rstrip('/')}"

    logger.warning(
        'AGENT_PUBLIC_URL and VCAP_APPLICATION are not set. Falling back to '
        'local HOST/PORT for the agent card URL.'
    )
    host = 'localhost' if HOST in {'0.0.0.0', '::'} else HOST
    return f'http://{host}:{PORT}'

# Create agent capabilities and card
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
    # Joule currently calls the app through the configured destination, but the
    # agent card should still advertise the correct public URL for A2A clients.
    url=get_public_url(),
    version='1.0.0',
    default_input_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    default_output_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    capabilities=capabilities,
    skills=[skill],
)

# Create request handler and server
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

# Export the ASGI app for uvicorn
app = server.build()
app = wrap_with_ias_auth(app)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
