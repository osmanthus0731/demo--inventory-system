# Meadow inventory showcase

This folder is an independent Flask website with fictional data and PIN-free demo accounts. Deploy this folder as its own repository and Vercel project.

## Vercel setup

1. Create a separate MongoDB Atlas database, for example `meadow_demo`. Give a database user read/write access only to that database. Atlas replica sets support the transactions required for approvals, dispatch and receiving.
2. Allow connections from the deployment in Atlas Network Access. Use the outbound addresses configured for your host where available.
3. In Vercel Settings → Environment Variables, add:

   | Name | Value |
   | --- | --- |
   | `DEMO_MONGO_URI` | Connection string for the demo database user |
   | `DEMO_MONGO_DB` | `meadow_demo` (must contain `demo`) |
   | `FLASK_SECRET` | One random secret of at least 32 characters |

   Generate the secret once: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep it unchanged across deployments so sessions stay valid. Set variables for Production, and Preview if you use preview deployments.
4. Import this repository in Vercel with the Flask framework preset. Keep the root directory at this folder; use default build settings. `app.py` exports the Flask application and dependencies come from `requirements.txt`.
5. Deploy, or redeploy after setting the variables. The first startup initializes a new empty database with fictional products and 210 days of synthetic history. Later startups preserve changes. Initialization publishes data atomically so concurrent cold starts cannot partially seed or reset it.

Use demo-only credentials. The bootstrap reads `DEMO_MONGO_URI` explicitly and disables Access and real sync. A populated database without the demo initialization marker is rejected without overwriting records.

## Using the showcase

- Maya and Noah: Admin; Eli: Worker. Select an account and click Login; there is no PIN.
- Inventory, search, pricing, stock map and warehouse simulator use fictional products.
- Quotations, proforma invoices, delivery orders and purchase orders support editing, preview, PDF export and normal document workflows.
- Workers submit stock requests; another Admin approves. An Admin cannot approve their own request, so use Noah for requests submitted by Maya.
- Dispatch, receiving, history and simulated Access changes share the persistent database. Access connections and Access numbering are simulated or bypassed.
- Forecasting and analytics use synthetic history. Accounts, settings, saved contacts and documents persist across workers and restarts.

The public demo is shared: recruiter changes are visible to other visitors. It does not reset on redeploy. To start fresh, configure a new empty database such as `meadow_demo_v2` and redeploy; the old database remains available.

## Run locally

Run `setup_demo.bat`, then `start_demo.bat`, and open http://127.0.0.1:5055.

Without demo database variables, local preview uses in-memory fictional data and resets when stopped. For persistence locally, copy `.env.example` to `.env` and enter the demo connection details and secret. Never commit `.env`.

Vercel startup reports a setup error if the URI or stable secret is missing. In-memory storage cannot reliably preserve records or login state across serverless instances.

## Updating this copy

This folder includes serverless storage and entry-point changes beyond the original local demo builder. Preserve these deployment files when updating features. Rebuilding over this folder using the main project's local demo generator would discard the serverless setup.
