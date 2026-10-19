# Local demonstration

This separate application uses fictional products and an in-memory database. It cannot connect to live MongoDB or Access. It resets whenever the process restarts.

Run `setup_demo.bat` once (internet required to install dependencies), then `start_demo.bat`. Open the address shown in the terminal. Close the terminal to stop it.

To publish it as a recruiter showcase, create a Render Web Service from this folder. The included `render.yaml` installs the demo-only requirements and starts the isolated demo app. All changes reset on restart or redeploy.

Vercel is also supported. Import this repository as a Vercel project and deploy it with the default settings. `api/index.py` starts the same isolated fictional demo; its in-memory changes can reset whenever Vercel recycles or scales the function.

Accounts: Maya and Noah are Admins; Eli is a Worker. Select any account and click Login. No PIN is required in the demo.

The generated demo uses Meadow branding and a fictional company/logo. Operational branding is not used in demo pages or generated documents.

The stock map is an invented single-floor warehouse: six shelves (DEMO1–DEMO6) and two receiving/dispatch bays (DEMO7–DEMO8). Its layout and stock locations are fictional and separate from the operational map.

1. As Eli, find Luma Airless Pump and choose Edit Stock. Change a quantity, choose Correction and submit the request. Stock stays unchanged.
2. Sign out and select Maya. Open Stock Requests and approve it. The demo simulates a successful sync; it never opens an Access file.
3. Submit another request as Maya. Only Noah can approve Maya's request.
4. Open Stock History and filter Microsoft Access to see simulated imported changes. The demo banner has a button to create another simulated change.
5. Open Stock Forecasting to see predictions computed from 210 days of synthetic sales, receipts and completed-day records. Models and suggested quantities are calculated by the real forecasting module.
6. Use Users to demonstrate role assignment and deletion. Account deletion retains history. Restart the demo to restore the original accounts and quantities.

To rebuild from the live application's source: run `python tools/build_local_demo.py` in the main repository. The builder copies only application code and fictional seed scripts, never `.env`, Access files, reports, backups or real records.
