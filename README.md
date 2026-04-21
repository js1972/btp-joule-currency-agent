# Joule A2A Currency Agent Example

This repository shows how to expose a custom Python AI agent to SAP Joule by:

1. running the agent as a remote A2A service on SAP BTP Cloud Foundry
2. defining a Joule capability in YAML
3. wiring a Joule scenario to call that remote agent through a function

The example agent is a `Currency Agent` that answers exchange-rate questions.

## Related Setup Guide

This repository focuses on the code and deployment artifacts. Before using this agent template, read the SAP Community blog post(s) by Felix Bartler from SAP:

- [Joule A2A: Connect Code-Based Agents into Joule](https://community.sap.com/t5/technology-blog-posts-by-sap/joule-a2a-connect-code-based-agents-into-joule/ba-p/14329279)
- [Joule A2A: Handling Multi-Turn Conversations](https://community.sap.com/t5/technology-blog-posts-by-sap/joule-a2a-handeling-multi-turn-conversations/ba-p/14377615)

The blog posts cover:

- which authorization roles a developer needs to use the Joule CLI
- how to install and set up the Joule CLI
- how to create the corresponding application in SAP Cloud Identity Services for Joule CLI access
- how to package and deploy the Joule capability with the Joule CLI
- how to launch and test the capability in a test Joule assistant
- how to deploy or update the capability in the main production Joule assistant in your landscape
- How to configure the Joule capability for multi-turn conversations.

Note:
- if your SAP Cloud Identity Services tenant enforces MFA, append the current MFA code to the end of your password when logging in with the Joule CLI

## End-to-End Flow

1. A user asks Joule a currency question.
2. Joule evaluates the scenario in `currency_agent_capability/scenarios/currency_agent_scenario.yaml`.
3. That scenario points to the function in `currency_agent_capability/functions/currency_agent_function.yaml`.
4. The function runs an `agent-request` against the system alias `CURRENCY_AGENT`.
5. The alias is declared in `currency_agent_capability/capability.sapdas.yaml` and maps to the SAP destination `CURRENCY_AGENT`.
6. That destination points to the deployed Python A2A service from the `app/` folder.
7. The Python service processes the request and returns an A2A response.
8. The function extracts the text result and returns it to Joule.

## Prerequisites

Before deploying this example, make sure you have:

- a SAP BTP subaccount with Joule enabled
- the Joule CLI installed
- a Cloud Identity application created for Joule CLI login
- an IAS application configured with an API permission/scope of your choice
- access to a Cloud Foundry org and space
- a SAP AI Core / Gen AI Hub setup with a running deployment for the model you want to use

## Python Dependency Note

The Python dependencies for this repo are intentionally pinned in
`app/requirements.txt`.

Important:

- `a2a-sdk` is pinned to `0.3.26`
- this repo does not yet support `a2a-sdk` `1.0.0`
- the rest of the direct Python dependencies are also pinned so installs stay
  reproducible even though this repository does not currently include a lockfile

Why `a2a-sdk` is pinned:

- `a2a-sdk` `1.0.0` introduced breaking changes and requires a migration
- this codebase currently uses the pre-1.0 server bootstrap and helper APIs
- the current app depends on types and helpers that changed in `1.0.0`, for
  example:
  - `A2AStarletteApplication`
  - `AgentCard.url`
  - `a2a.utils.new_agent_text_message`
  - `a2a.utils.new_task`
  - `TextPart`
  - older task-state enum names

What that means for this project:

- upgrading `a2a-sdk` to `1.0.0` is not a safe version bump
- the app bootstrap in `app/app.py` and the executor adapter in
  `app/agent_executor.py` both need code changes
- until that migration is done and validated against Joule end to end, this
  repo stays on `a2a-sdk==0.3.26`

If you want to migrate this project to `a2a-sdk` `1.0.0`, follow the upstream
migration guide first:

[A2A Python SDK v1.0 migration guide](https://github.com/a2aproject/a2a-python/blob/main/docs/migrations/v1_0/README.md)

## Deploy The Python Agent To Cloud Foundry

Run from the `app/` folder:

```bash
cd app
cf login
cf target -o <org> -s <space>
cf push --no-start --random-route
```

Use `--random-route` only the first time if the default route is already taken.
After the first successful deployment, normal `cf push` should keep the existing route.

### Set Cloud Foundry Environment Variables

Set all required values on the deployed app.

AI Core / Gen AI Hub values:

```bash
cf set-env currency-agent AICORE_AUTH_URL '<auth-url>'
cf set-env currency-agent AICORE_CLIENT_ID '<client-id>'
cf set-env currency-agent AICORE_CLIENT_SECRET '<client-secret>'
cf set-env currency-agent AICORE_RESOURCE_GROUP '<resource-group>'
cf set-env currency-agent AICORE_BASE_URL '<base-url>'
```

IAS protection values:

```bash
cf set-env currency-agent IAS_ISSUER '<ias-issuer-url>'
cf set-env currency-agent IAS_AUDIENCE '<ias-client-id>'
cf set-env currency-agent IAS_REQUIRED_SCOPE '<ias-api-permission>'
```

Example:

```bash
cf set-env currency-agent AICORE_AUTH_URL 'https://<ai-core-auth-host>'
cf set-env currency-agent AICORE_CLIENT_ID '***'
cf set-env currency-agent AICORE_CLIENT_SECRET '***'
cf set-env currency-agent AICORE_RESOURCE_GROUP '<resource-group>'
cf set-env currency-agent AICORE_BASE_URL 'https://<ai-core-api-host>'
cf set-env currency-agent IAS_ISSUER 'https://<ias-tenant>.accounts.cloud.sap'
cf set-env currency-agent IAS_AUDIENCE '12345678-1234-1234-1234-123456789abc'
cf set-env currency-agent IAS_REQUIRED_SCOPE 'api_read_access'
cf set-env currency-agent LOG_LEVEL 'INFO'
cf set-env currency-agent LOG_PAYLOADS 'false'
```

Then restart or restage:

```bash
cf restart currency-agent
```

or

```bash
cf restage currency-agent
```

### Important Notes About Environment Variables

- keep secrets out of `manifest.yaml`
- this repo intentionally does not store AI Core credentials in the manifest
- if you paste literal credentials into `cf set-env`, use single quotes so shell special characters are preserved
- if you already exported shell variables locally, use double quotes around variable expansion, for example:
  `cf set-env currency-agent AICORE_CLIENT_SECRET "$AICORE_CLIENT_SECRET"`

### Logging Configuration

The app uses safe operational logging by default.

Supported logging environment variables:

- `LOG_LEVEL`
  Controls the Python log level. Recommended default: `INFO`
- `LOG_PAYLOADS`
  Controls whether request, agent-stream, and tool payloads are logged at `DEBUG` level. Recommended default: `false`

Example:

```bash
cf set-env currency-agent LOG_LEVEL 'DEBUG'
cf set-env currency-agent LOG_PAYLOADS 'true'
cf restart currency-agent
```

Logging behavior:

- `INFO`
  logs only safe correlation details such as task ID, context ID, request start, and request completion
- `DEBUG` with `LOG_PAYLOADS=true`
  additionally logs inbound user queries, agent stream items, tool arguments, and upstream tool responses for debugging
- raw framework object dumps are intentionally not logged
- do not leave `LOG_PAYLOADS=true` enabled in shared or production environments unless you explicitly want payload-level debugging

### Important Notes About AI Core Values

Use the exact values from the AI Core service key.

For this working setup:

- `AICORE_AUTH_URL`
  Use the raw auth URL from the service key.
  Do not append `/oauth/token` for this project setup.
- `AICORE_CLIENT_ID`
  Use the `clientid` from the service key.
- `AICORE_CLIENT_SECRET`
  Use the `clientsecret` from the service key.
- `AICORE_BASE_URL`
  Use the AI Core API base URL from the service key.
- `AICORE_RESOURCE_GROUP`
  Use the correct resource group name.

### Important Notes About IAS Values

The end-to-end auth model is:

- the BTP destination uses `OAuth2ClientCredentials` to obtain a token from IAS
- the Python agent validates the resulting bearer JWT on every request

Important:
- `IAS_ISSUER` is the issuer/base URL, for example:
  `https://<ias-tenant>.accounts.cloud.sap`
- do not append `/oauth2/token` to `IAS_ISSUER`
- `IAS_AUDIENCE` should be the IAS application client ID
- `IAS_REQUIRED_SCOPE` should match whatever API permission/scope you configured in IAS
- a convenient way to confirm the issuer for your tenant is:
  `https://<ias-tenant>.accounts.cloud.sap/.well-known/openid-configuration`
- the issuer value used in `IAS_ISSUER` should match the issuer/base URL for that tenant, not the token endpoint

Security behavior:
- the app now fails closed by default
- if `IAS_ISSUER` or `IAS_AUDIENCE` is missing, the app will not start
- the only bypass is setting `ALLOW_UNAUTHENTICATED=true`, which should be used only for deliberate local or temporary test scenarios

### Verify The App Is Running

```bash
cf app currency-agent
cf logs currency-agent --recent
```

A successful result should show:
- `requested state: started`
- `instances: 1/1`
- `#0 running`

### Agent Card URL

The Python app publishes an A2A `AgentCard`, and that card includes a `url` field.

Current behavior:

- if `AGENT_PUBLIC_URL` is set, the app uses that value for the agent card URL
- otherwise, the app uses the first route from Cloud Foundry `VCAP_APPLICATION.application_uris`
- otherwise, for local development only, it falls back to `http://localhost:<PORT>`

Important:

- for the current Joule integration, Joule does not rely on the `AgentCard.url`
- Joule calls the agent through the BTP destination referenced by the `CURRENCY_AGENT` system alias
- the agent card URL is still important for correctness and for broader A2A interoperability outside this specific Joule flow

Example override:

```bash
cf set-env currency-agent AGENT_PUBLIC_URL 'https://<public-front-door-url>'
cf restart currency-agent
```

Use `AGENT_PUBLIC_URL` when the public URL that clients should see is not the raw Cloud Foundry app route, for example when using:

- App Router
- API Management
- a custom domain
- any other front-door or proxy URL

## Template Limitations

This repository is intentionally a simple working template, not a production-ready agent runtime.

Current demo-oriented tradeoffs:

- task state, push-notification config, and LangGraph checkpoint state are stored in memory only
- that state will not survive app restarts
- that state is not shared across multiple Cloud Foundry instances
- the exchange-rate tool uses a blocking HTTP call for simplicity

What this means:

- this template is best treated as a single-instance demo or learning project
- if you scale the app horizontally or restart it, active task/conversation state can be lost
- the current blocking tool call pattern is fine for a low-traffic sample, but not ideal for a busier service

Typical improvements for real agents built from this template:

- replace in-memory task and checkpoint storage with durable backing stores
- use a database or Redis-style shared store when state must survive restarts or be shared across instances
- for LangGraph specifically, use a durable checkpointer instead of `MemorySaver`
- replace blocking tool calls with async I/O or move blocking work off the event loop

## Model Configuration

The model is configured in `app/agent.py`.

Current working setting:

```python
self.model = ChatOpenAI(
    proxy_model_name='gpt-5-mini',
    proxy_client=proxy_client,
    temperature=0
)
```

Important:
- the model name must correspond to a running deployment in your AI Core / Gen AI Hub resource group
- if not, the app will fail during startup with an error like:
  `No deployment found ... deployment.model_name == <model-name>`

## Create The BTP Destination

Create an HTTP destination in the BTP subaccount:

- `Name`: `CURRENCY_AGENT`
- `Type`: `HTTP`
- `URL`: the Cloud Foundry route of the deployed Python app
- `Proxy Type`: `Internet`
- `Authentication`: `OAuth2ClientCredentials`
- `Client ID`: the IAS application client ID
- `Client Secret`: the IAS application client secret
- `Token Service URL`: `https://<ias-tenant>.accounts.cloud.sap/oauth2/token`
- `Token Service URL Type`: `Dedicated`
- `Use Basic credentials for Token Service`: enabled

Example destination values:

- `Name`: `CURRENCY_AGENT`
- `Type`: `HTTP`
- `URL`: `https://currency-agent-<route>.cfapps.us10.hana.ondemand.com`
- `Proxy Type`: `Internet`
- `Authentication`: `OAuth2ClientCredentials`
- `Client ID`: `12345678-1234-1234-1234-123456789abc`
- `Client Secret`: `<your-ias-client-secret>`
- `Token Service URL`: `https://<ias-tenant>.accounts.cloud.sap/oauth2/token`
- `Token Service URL Type`: `Dedicated`
- `Use Basic credentials for Token Service`: enabled

Important:
- the destination name must match the alias mapping in `currency_agent_capability/capability.sapdas.yaml`
- the destination should point directly to the Python app URL
- the destination client must be authorized in IAS for the same API permission/scope configured in `IAS_REQUIRED_SCOPE`
- the destination token endpoint uses `/oauth2/token`
- this is different from `IAS_ISSUER`, which should remain the base issuer URL without `/oauth2/token`

## Deploy The Joule Capability

Run from the repository root, not from `currency_agent_capability/`:

```bash
cd ..
joule login
joule deploy -c -n "currency_agent_test"
joule launch "currency_agent_test"
```

Why from the repo root:
- the CLI entry point is `da.sapdas.yaml`
- that file points to `./currency_agent_capability`

## Testing

After deployment:

1. confirm the Python app is running in Cloud Foundry
2. confirm an unauthenticated direct call to the Python app returns `401`
3. confirm the destination `CURRENCY_AGENT` points to the correct route and uses `OAuth2ClientCredentials`
4. deploy the capability into a test assistant
5. launch the test assistant and ask a currency question

Example prompts:
- `What is the exchange rate between USD and GBP?`
- `How much is 10 USD in INR?`

## Troubleshooting

### Route conflict on `cf push`

If `cf push` fails because the route already exists:

```bash
cf push --no-start --random-route
```

Use this only to get the first successful unique route.

### App crashes with `invalid_client`

This means the AI Core credentials are wrong.
Check:
- `AICORE_AUTH_URL`
- `AICORE_CLIENT_ID`
- `AICORE_CLIENT_SECRET`

### App crashes with `No deployment found`

This means the selected model does not have a running deployment in the AI Core resource group.
Either:
- create a deployment for that model in SAP AI Launchpad / AI Core
- or change the code to a model that already has a running deployment

### Joule capability deploys but is not selected

Check the description in:
- `currency_agent_capability/scenarios/currency_agent_scenario.yaml`

That description is the main routing hint Joule uses during scenario selection.

## Security Note

The current code now enforces IAS JWT validation on every inbound request, while the BTP destination uses OAuth2 client credentials to obtain the bearer token from IAS.

Current behavior:
- requests without a bearer token return `401`
- requests with an invalid token return `401`
- requests missing the API permission/scope configured in `IAS_REQUIRED_SCOPE` return `401`
- the app will not start if `IAS_ISSUER` or `IAS_AUDIENCE` is missing

For Joule integration:
- the BTP destination must use `OAuth2ClientCredentials`
- the destination token service URL should be the IAS token endpoint, for example:
  `https://<ias-tenant>.accounts.cloud.sap/oauth2/token`

For production hardening:
- add rate limiting and cost-control guardrails before exposing the agent beyond basic testing
- this can be done at the edge, in-app, or both, depending on your landscape architecture
- the current template does not implement rate limiting

## Additional Troubleshooting Reference

For Joule-specific troubleshooting when deploying custom capabilities, see:

[Extending SAP Joule with Custom DAS Capabilities](https://community.sap.com/t5/technology-blog-posts-by-sap/extending-sap-joule-with-custom-das-capabilities/ba-p/14359358)

This is especially useful for:

- checking whether the capability is deployed in the expected assistant
- validating scenario selection behavior in Joule
- diagnosing dialog function execution failures
- investigating custom capability issues after the basic setup steps from the first blog are already complete
- reviewing common end-to-end setup issues across Joule, destinations, and capability deployment

## Understanding The Code

### How The SAP YAML Files Work Together

#### `currency_agent_capability/capability.sapdas.yaml`

Defines the capability package and the remote system alias.

Responsibilities:
- gives the capability its identity and metadata
- declares the required `joule.ext` namespace
- maps the system alias `CURRENCY_AGENT` to the SAP destination `CURRENCY_AGENT`

#### `currency_agent_capability/functions/currency_agent_function.yaml`

Defines what Joule executes when the scenario is selected.

Responsibilities:
- sends an `agent-request` to the remote A2A service
- stores the result in `apiResponse`
- extracts `apiResponse.body.artifacts[0].parts[0].text`
- returns that text back to Joule

#### `currency_agent_capability/scenarios/currency_agent_scenario.yaml`

Defines the Joule-facing scenario.

Responsibilities:
- provides the description Joule uses during scenario selection
- points to the target function `currency_agent_function`

Important:
- the scenario `description` is one of the most important fields in the project
- it is the main routing hint Joule uses to decide whether this scenario matches a user request
- if the description is too vague, routing may fail
- if multiple scenarios have very similar descriptions, Joule selection quality will get worse

Recommended style for scenario descriptions:
- 1 to 3 sentences
- specific and scoped
- explicit business vocabulary
- no generic marketing language

### How The Python Files Work Together

#### `app/app.py`

Server bootstrap.

Responsibilities:
- loads environment variables
- creates the A2A `AgentCard`
- creates the request handler and task stores
- registers `CurrencyAgentExecutor`
- builds the ASGI app for `uvicorn`

#### `app/agent.py`

Actual agent logic.

Responsibilities:
- defines the `get_exchange_rate` tool
- defines the structured response format
- constructs the LangGraph ReAct agent
- configures the model through SAP Gen AI Hub / AI Core
- streams progress and final results

#### `app/agent_executor.py`

A2A protocol adapter.

Responsibilities:
- receives the A2A request context
- creates or resumes tasks
- calls `CurrencyAgent.stream()`
- converts agent output into A2A task status updates and artifacts

### Project Structure

#### Root

- `README.md`
  Main project documentation.
- `da.sapdas.yaml`
  Top-level Joule deployment descriptor pointing to `./currency_agent_capability`.
- `commands.txt`
  Joule CLI cheat-sheet.

#### Python App

- `app/app.py`
- `app/agent.py`
- `app/agent_executor.py`
- `app/manifest.yaml`
- `app/requirements.txt`
- `app/runtime.txt`

#### Joule Capability

- `currency_agent_capability/capability.sapdas.yaml`
- `currency_agent_capability/functions/currency_agent_function.yaml`
- `currency_agent_capability/scenarios/currency_agent_scenario.yaml`
