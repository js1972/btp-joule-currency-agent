# Joule A2A Currency Agent Example

This repository shows how to expose a custom Python AI agent to SAP Joule by:

1. running the agent as a remote A2A service on SAP BTP Cloud Foundry
2. defining a Joule capability in YAML
3. wiring a Joule scenario to call that remote agent through a function

The example agent is a `Currency Agent` that answers exchange-rate questions.

## End-to-End Flow

1. A user asks Joule a currency question.
2. Joule evaluates the scenario in `currency_agent_capability/scenarios/currency_agent_scenario.yaml`.
3. That scenario points to the function in `currency_agent_capability/functions/currency_agent_function.yaml`.
4. The function runs an `agent-request` against the system alias `CURRENCY_AGENT`.
5. The alias is declared in `currency_agent_capability/capability.sapdas.yaml` and maps to the SAP destination `CURRENCY_AGENT`.
6. That destination points to the deployed Python A2A service from the `app/` folder.
7. The Python service processes the request and returns an A2A response.
8. The function extracts the text result and returns it to Joule.

## How The SAP YAML Files Work Together

### `currency_agent_capability/capability.sapdas.yaml`

Defines the capability package and the remote system alias.

Responsibilities:
- gives the capability its identity and metadata
- declares the required `joule.ext` namespace
- maps the system alias `CURRENCY_AGENT` to the SAP destination `CURRENCY_AGENT`

### `currency_agent_capability/functions/currency_agent_function.yaml`

Defines what Joule executes when the scenario is selected.

Responsibilities:
- sends an `agent-request` to the remote A2A service
- stores the result in `apiResponse`
- extracts `apiResponse.body.artifacts[0].parts[0].text`
- returns that text back to Joule

### `currency_agent_capability/scenarios/currency_agent_scenario.yaml`

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

## How The Python Files Work Together

### `app/app.py`

Server bootstrap.

Responsibilities:
- loads environment variables
- creates the A2A `AgentCard`
- creates the request handler and task stores
- registers `CurrencyAgentExecutor`
- builds the ASGI app for `uvicorn`

### `app/agent.py`

Actual agent logic.

Responsibilities:
- defines the `get_exchange_rate` tool
- defines the structured response format
- constructs the LangGraph ReAct agent
- configures the model through SAP Gen AI Hub / AI Core
- streams progress and final results

### `app/agent_executor.py`

A2A protocol adapter.

Responsibilities:
- receives the A2A request context
- creates or resumes tasks
- calls `CurrencyAgent.stream()`
- converts agent output into A2A task status updates and artifacts

### `app/test_client.py`

Manual client for testing the deployed A2A endpoint without Joule.

## Project Structure

### Root

- `README.md`
  Main project documentation.
- `da.sapdas.yaml`
  Top-level Joule deployment descriptor pointing to `./currency_agent_capability`.
- `commands.txt`
  Joule CLI cheat-sheet.
- `blog.md`
  Longer article-style walkthrough.
- `blog_shit.md`
  Alternate or draft documentation.

### Python App

- `app/app.py`
- `app/agent.py`
- `app/agent_executor.py`
- `app/test_client.py`
- `app/manifest.yaml`
- `app/requirements.txt`
- `app/runtime.txt`

### Joule Capability

- `currency_agent_capability/capability.sapdas.yaml`
- `currency_agent_capability/functions/currency_agent_function.yaml`
- `currency_agent_capability/scenarios/currency_agent_scenario.yaml`

## Prerequisites

Before deploying this example, make sure you have:

- a SAP BTP subaccount with Joule enabled
- the Joule CLI installed
- a Cloud Identity application created for Joule CLI login
- access to a Cloud Foundry org and space
- a SAP AI Core / Gen AI Hub setup with a running deployment for the model you want to use

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

### Set AI Core Environment Variables

Set the required values on the deployed app:

```bash
cf set-env currency-agent AICORE_AUTH_URL '<auth-url>'
cf set-env currency-agent AICORE_CLIENT_ID '<client-id>'
cf set-env currency-agent AICORE_CLIENT_SECRET '<client-secret>'
cf set-env currency-agent AICORE_RESOURCE_GROUP '<resource-group>'
cf set-env currency-agent AICORE_BASE_URL '<base-url>'
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

### Verify The App Is Running

```bash
cf app currency-agent
cf logs currency-agent --recent
```

A successful result should show:
- `requested state: started`
- `instances: 1/1`
- `#0 running`

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
- `Authentication`: `NoAuthentication` for the initial end-to-end test

Important:
- the destination name must match the alias mapping in `currency_agent_capability/capability.sapdas.yaml`
- for the initial test, the destination should point directly to the Python app URL

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
2. confirm the destination `CURRENCY_AGENT` points to the correct route
3. deploy the capability into a test assistant
4. launch the test assistant and ask a currency question

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

The current working setup uses `NoAuthentication` on the destination to prove the end-to-end flow.

That is acceptable for an initial test in a controlled environment, but it should not be the final design.

Important:
- there is currently no authorization check on this agent endpoint
- the deployed Cloud Foundry route is effectively open to the world
- the current setup should be treated as a temporary development or test-only configuration

TODO:
- add authentication and authorization using OAuth client credentials flow with SAP Cloud Identity Services
- update the BTP destination to use the protected endpoint instead of `NoAuthentication`
