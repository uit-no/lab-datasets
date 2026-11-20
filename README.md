# labcat – lab dataset catalog

A small web app that lists every dataset the lab has collected: what it is, where the
data and backups live, and which papers, preprints and code belong to it. See
[PLAN.md](PLAN.md) for the full proposal. This is the **local-only** first version:
no login (every change is made as `matthias`), no Slack, no server.

## Two git repos

| Repo | Where | Contents |
|---|---|---|
| App | this folder | Python code (FastAPI + Jinja2 + htmx), tests |
| Catalog data | `data/` (own git repo, ignored by the app repo) | `datasets/*.yaml`, `people.yaml`, `vocab/`, `schema/` |

Every save in the web app is a commit in `data/`, authored by the person who made it
(committer: "Lab catalog"). The data repo is
[cogneuro-uit/lab-datasets-data](https://github.com/cogneuro-uit/lab-datasets-data): the
app pulls before each save, pushes after it, and syncs every 10 minutes
(`LABCAT_PULL_INTERVAL`). Admins (`LABCAT_ADMINS`) have an *Admin* page with the sync status
and a *Sync now* button, e.g. after pushing a hand edit. If a sync fails (GitHub unreachable,
or a conflict with a hand edit), changes stay saved on the server and everyone sees a notice
until it works again.

## Quick start

```bash
uv run labcat init      # once: creates data/ (already done)
uv run labcat serve     # http://localhost:8420
```

Other commands: `labcat validate` (check all YAML files), `labcat schema` (regenerate
the JSON schema). Settings come from environment variables or a `.env` file (see
[.env.example](.env.example)): `LABCAT_DATA` (data repo path, default `./data`),
`LABCAT_USER` (person id edits are attributed to when Slack login is off, default `matthias`).

## Sign in with Slack

Without Slack credentials the app runs in development mode: no login, every change is
made as `LABCAT_USER`. With them, everyone must sign in with Slack, and each change is
committed as the signed-in person. People are matched in `people.yaml` by Slack ID, then
by email; someone signing in for the first time is added automatically.

1. Create a Slack app at https://api.slack.com/apps → *From a manifest*, with the user
   scopes `openid`, `profile`, `email` and the redirect URL `<address>/auth/callback`.
   Slack only accepts **https** redirect URLs.
2. Copy `.env.example` to `.env` and fill in the client ID and secret, a secret key, and
   `LABCAT_SLACK_TEAM_ID` (so only the lab's workspace can sign in).
3. Locally, serve https with a trusted certificate from mkcert:
   ```bash
   mkdir -p certs && mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost
   uv run labcat serve --https     # https://localhost:8420
   ```

To keep it running in the background, see [deploy/labcat.service](deploy/labcat.service).

## Deploy to Azure App Service

The [GitHub Actions workflow](.github/workflows/p-resapp-labdata-deploy.yaml) tests
the app with `uv`, builds a ZIP with its locked runtime dependencies, and deploys
it to the `staging` slot of `p-resapp-labdata-webapp` when run manually from
`main` in the Actions tab. Validate the staging site at
`p-resapp-labdata-webapp-staging`, then run the separate
[swap workflow](.github/workflows/p-resapp-labdata-swap.yaml) from `main` to
promote it to production.

Before the first deployment:

1. Configure Azure OIDC federation for the repository's `main` branch
   (`repo:uit-no/lab-datasets:ref:refs/heads/main`). Grant the federated identity
   permission to deploy to the staging slot, read the Web App, and swap slots.
   Set these GitHub Actions secrets: `P_RESAPP_DEPLOYMENT_ID_CLIENTID`,
   `P_RESAPP_DEPLOYMENT_ID_TENANTID`, and
   `P_RESAPP_DEPLOYMENT_ID_SUBSCRIPTIONID`.
2. Set the Web App's stack to **Python 3.12 on Linux**. Set
   `SCM_DO_BUILD_DURING_DEPLOYMENT=false` because the runner builds the ZIP, and
   leave `WEBSITE_RUN_FROM_PACKAGE` unset. Set the startup command to:
   ```sh
   python -m uvicorn labcat.web:app_factory --factory --host 0.0.0.0 --port 8000
   ```
3. Pick a persistent path outside the deployment directory for the catalog data
   checkout, such as `/home/labcat-data`, and set `LABCAT_DATA` to it. Set
   `LABCAT_DATA_REMOTE` to the data repository's HTTPS address and
   `LABCAT_GIT_TOKEN` to a fine-grained GitHub token with read/write *Contents*
   access to that repository only. If the checkout is missing, the app clones it
   at startup; it then pulls and pushes with the token. A checkout of another
   repository (or one without a remote) is renamed to `<name>.old-<time>` and
   replaced by a fresh clone. The workflow's Azure
   credentials are only for deployment.
4. In App Service, enable **HTTPS Only** and set these required environment
   variables under **Environment variables**:
   - `LABCAT_DATA`: path to the catalog Git checkout.
   - `LABCAT_DATA_REMOTE` and `LABCAT_GIT_TOKEN` (see step 3; not checked at
     startup, since an existing checkout with its own credentials also works).
   - `LABCAT_SLACK_CLIENT_ID` and `LABCAT_SLACK_CLIENT_SECRET`: Slack app credentials.
   - `LABCAT_SLACK_TEAM_ID`: the only Slack workspace allowed to sign in.
   - `LABCAT_SECRET_KEY`: a stable, randomly generated session signing key.
   - `LABCAT_BASE_URL`: the public HTTPS origin, e.g. `https://datasets.lab.uit.no`.
     Register `<LABCAT_BASE_URL>/auth/callback` in the Slack app.

   The production startup command refuses to start if any of these are missing
   or blank, or if the base URL is not an HTTPS origin. It reads these settings
   from the environment, not `.env`. Use `labcat serve` for local development.
5. Mark `LABCAT_BASE_URL`, `LABCAT_DATA` and `LABCAT_SANDBOX` as *deployment
   slot settings*, so they stay with their slot when staging and production are
   swapped. On the staging slot, set `LABCAT_BASE_URL` to the staging address and
   `LABCAT_SANDBOX=1`: changes made there are never pushed, and each sync resets
   its checkout to the GitHub version. Register the callback URL of both slots
   in the Slack app.

### Git checkout ownership on App Service

Make sure Git is available in the runtime image. When the app clones the
checkout itself, it belongs to the account that runs the web app, so no
`safe.directory` exception is needed. From a shell running as that same account, test the checkout with
`git -C "$LABCAT_DATA" status --short`.

If Git reports dubious ownership and the ownership mismatch is intentional,
first verify that the directory is the expected checkout and is writable only
by trusted accounts. Then, as the runtime user, configure the exact checkout
once (substitute your actual path):

```sh
checkout=$(realpath -e /home/labcat-data) &&
  git config --global --fixed-value --replace-all safe.directory "$checkout" "$checkout"
```

This adds the path if absent and replaces duplicate entries for that path if
rerun, without modifying exceptions for other checkouts. Never use `*`. If the
runtime user's global Git config is not persistent across container recreation,
fix checkout ownership instead or provision the exception in a protected,
persistent global config read by the app. Remove the `git config --global --add`
line from the startup command once the checkout works under the runtime user.

## Adding datasets

- **Step by step:** a wizard with seven short steps; only the first is required.
- **Quick placeholder:** title + contact, fill in the rest later.
- **Import YAML:** upload or paste; it is checked before saving. See `examples/`
  (fictional datasets) for the format.
- **With an AI assistant:** "Download skill" on the *Add a dataset* page gives a zip
  (`lab-dataset-yaml`) for Claude or other agents. It interviews the user, writes the YAML
  and checks it with a bundled validator. It's built on request with the current people
  (names and Slack handles only), tags, modalities and dataset IDs. The source is in
  `src/labcat/skill/`.

## Development

```bash
uv run pytest
uv run labcat serve --reload
```

Frontend libraries are vendored in `src/labcat/static/vendor/` (htmx 2.0.11,
MiniSearch 7.2.0); icons are a sprite built from lucide-static by `scripts/build_icons.py`.
