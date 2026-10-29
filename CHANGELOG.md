# Changelog

## [0.14.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.13.0...v0.14.0) (2026-10-29)


### Features

* **ops:** a Cloudflare Worker maintenance page for when the origin itself is down ([#194](https://github.com/hamza-aziz-ai/HalalLens/issues/194)) ([3e4dca7](https://github.com/hamza-aziz-ai/HalalLens/commit/3e4dca7e6b761140faf2f6ef838eecc4b8ddb427))


### Bug Fixes

* **auth:** a failed Google sign-in returns to the login page with a message, never a raw JSON error ([#195](https://github.com/hamza-aziz-ai/HalalLens/issues/195)) ([daaa919](https://github.com/hamza-aziz-ai/HalalLens/commit/daaa9194743cd72cc9c6874f4ac117bac7ea30d8))

## [0.13.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.12.0...v0.13.0) (2026-10-29)


### Features

* **billing:** purchases queue behind paid time instead of replacing it; Switch, Extend and Lifetime rules ([#196](https://github.com/hamza-aziz-ai/HalalLens/issues/196)) ([8fd9000](https://github.com/hamza-aziz-ai/HalalLens/commit/8fd9000d299f044e119da7af9eb937e539dfc925))

## [0.12.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.11.2...v0.12.0) (2026-10-29)


### Features

* **ui:** a maintenance page during restarts, a 404 page, and readable API errors ([#191](https://github.com/hamza-aziz-ai/HalalLens/issues/191)) ([7e52587](https://github.com/hamza-aziz-ai/HalalLens/commit/7e52587ea548fac358ad6edff2b9093a32f84bff))


### Bug Fixes

* **narrator:** ask the Ollama model for high reasoning effort on financial explanations ([#190](https://github.com/hamza-aziz-ai/HalalLens/issues/190)) ([7cfe58b](https://github.com/hamza-aziz-ai/HalalLens/commit/7cfe58b42dfbddc9ed2c6aa2204625dab12795e9))

## [0.11.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.11.1...v0.11.2) (2026-10-29)


### Bug Fixes

* **billing:** a Razorpay refund webhook now actually revokes the plan ([#188](https://github.com/hamza-aziz-ai/HalalLens/issues/188)) ([dc66190](https://github.com/hamza-aziz-ai/HalalLens/commit/dc66190a69417fdb1289193078c590b684e3a369))

## [0.11.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.11.0...v0.11.1) (2026-10-29)


### Bug Fixes

* **ops:** read .env values without carriage returns in the deploy script ([#186](https://github.com/hamza-aziz-ai/HalalLens/issues/186)) ([714029b](https://github.com/hamza-aziz-ai/HalalLens/commit/714029bc6a9f88f7593bf4d8891c63bd8a84763c))

## [0.11.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.10.0...v0.11.0) (2026-10-29)


### Features

* **llm:** LLM narration through a signed-in Ollama daemon (gpt-oss:120b-cloud), with a call cap and circuit breaker ([#181](https://github.com/hamza-aziz-ai/HalalLens/issues/181)) ([435c8e7](https://github.com/hamza-aziz-ai/HalalLens/commit/435c8e7d85f89c8153b1d4c3e05209e5cf95a102))

## [0.10.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.9.0...v0.10.0) (2026-10-29)


### Features

* **ops:** pull-only deploys from the published images, with the deploy script in the repository ([#180](https://github.com/hamza-aziz-ai/HalalLens/issues/180)) ([2a6b991](https://github.com/hamza-aziz-ai/HalalLens/commit/2a6b991ef7cfa666241764ff06fe98cc7e5247ae))

## [0.9.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.8.0...v0.9.0) (2026-10-29)


### Features

* **ui:** Products & pricing page, site footer, configurable support email, checkout cancel handling ([#178](https://github.com/hamza-aziz-ai/HalalLens/issues/178)) ([cde5a01](https://github.com/hamza-aziz-ai/HalalLens/commit/cde5a01c6e60506c63fa96ea70d116d2a86ac74f))

## [0.8.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.7.2...v0.8.0) (2026-10-29)


### Features

* **auth:** browser-bound Google sign-in and explicit "Link Google account" ([#173](https://github.com/hamza-aziz-ai/HalalLens/issues/173)) ([5fb2f0d](https://github.com/hamza-aziz-ai/HalalLens/commit/5fb2f0d6e2d0e0ecaa3773d78762f07835f19134))

## [0.7.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.7.1...v0.7.2) (2026-10-29)


### Bug Fixes

* **auth:** email-first sign-up, password reset, and no admin or Google linking from an unproven email ([#172](https://github.com/hamza-aziz-ai/HalalLens/issues/172)) ([b32da3a](https://github.com/hamza-aziz-ai/HalalLens/commit/b32da3a8e200c5dea77bd15d0153b15158476af4))

## [0.7.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.7.0...v0.7.1) (2026-10-29)


### Bug Fixes

* **ui:** apply Alpine security updates in the dashboard image ([#170](https://github.com/hamza-aziz-ai/HalalLens/issues/170)) ([e24f783](https://github.com/hamza-aziz-ai/HalalLens/commit/e24f783a9b416a7e2a7279e665e8195bb81f8376))

## [0.7.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.3...v0.7.0) (2026-10-29)


### Features

* **alerts:** store watchlists in PostgreSQL and detect flips with conditional updates ([#163](https://github.com/hamza-aziz-ai/HalalLens/issues/163)) ([2db63cd](https://github.com/hamza-aziz-ai/HalalLens/commit/2db63cd8707177bda3b20ffb159a5e40807f1717))


### Bug Fixes

* **ui:** upgrade to Next.js 16 and React 19, with ESLint 9 flat config ([#164](https://github.com/hamza-aziz-ai/HalalLens/issues/164)) ([6b174bc](https://github.com/hamza-aziz-ai/HalalLens/commit/6b174bcb944b1fd6ac90a567aed5577101df57d8))

## [0.6.3](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.2...v0.6.3) (2026-10-29)


### Bug Fixes

* **crawler:** fetch every page of a company's BSE announcements ([#159](https://github.com/hamza-aziz-ai/HalalLens/issues/159)) ([0d881a6](https://github.com/hamza-aziz-ai/HalalLens/commit/0d881a68c3acb256b9221d1e4d53f5744dd4d345))
* **market-data:** stop caching Indian Stock API failures for the life of the process ([#156](https://github.com/hamza-aziz-ai/HalalLens/issues/156)) ([ad60ede](https://github.com/hamza-aziz-ai/HalalLens/commit/ad60ede5ff868fed82d5cb36272778aa5dc7c893))

## [0.6.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.1...v0.6.2) (2026-10-29)


### Bug Fixes

* **etl:** detect amount scale from whole unit words, not substrings ([#158](https://github.com/hamza-aziz-ai/HalalLens/issues/158)) ([db0c6c0](https://github.com/hamza-aziz-ai/HalalLens/commit/db0c6c08f56ba02edc8ba224e16f50c1e23807df))

## [0.6.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.0...v0.6.1) (2026-10-29)


### Bug Fixes

* **ui:** manual analysis no longer fails for free users on the paid /narrate call ([#155](https://github.com/hamza-aziz-ai/HalalLens/issues/155)) ([08bebb3](https://github.com/hamza-aziz-ai/HalalLens/commit/08bebb30761c7c34c95bd018e6f0fac982f683b2))

## [0.6.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.3...v0.6.0) (2026-10-29)


### Features

* **ops:** nightly PostgreSQL backups to the object store with 14-day retention ([#152](https://github.com/hamza-aziz-ai/HalalLens/issues/152)) ([a17e2fd](https://github.com/hamza-aziz-ai/HalalLens/commit/a17e2fd34e0dd192de91549a6c66915783a8a31d))

## [0.5.3](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.2...v0.5.3) (2026-10-29)


### Bug Fixes

* **market-data:** read the current BSE and NSE bhavcopy files ([#150](https://github.com/hamza-aziz-ai/HalalLens/issues/150)) ([9522273](https://github.com/hamza-aziz-ai/HalalLens/commit/95222736ab6835d48fba351d68a4e54a951602b7))

## [0.5.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.1...v0.5.2) (2026-10-28)


### Bug Fixes

* **ui:** serve the dashboard image as static files, without Next.js or Node.js at runtime ([#147](https://github.com/hamza-aziz-ai/HalalLens/issues/147)) ([fe2c29b](https://github.com/hamza-aziz-ai/HalalLens/commit/fe2c29b3b871cdbdd32f3f4f647975d57e427f12))

## [0.5.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.0...v0.5.1) (2026-10-28)


### Bug Fixes

* **market-data:** cap Indian Stock API calls per month and stop sending the key in URLs ([#145](https://github.com/hamza-aziz-ai/HalalLens/issues/145)) ([0b36511](https://github.com/hamza-aziz-ai/HalalLens/commit/0b3651104dee02c56d17f96812c488d87821231e))

## [0.5.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.4.0...v0.5.0) (2026-10-28)


### Features

* **deploy:** add a Cloudflare Tunnel mode beside Caddy's own TLS ([#134](https://github.com/hamza-aziz-ai/HalalLens/issues/134)) ([0194ee3](https://github.com/hamza-aziz-ai/HalalLens/commit/0194ee3d4e7ad51801ffeb4a576c0a2a0f105b64))

## [0.4.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.3.0...v0.4.0) (2026-10-28)


### Features

* **storage:** store filing PDFs in Cloudflare R2; drop the unavailable MinIO image ([#131](https://github.com/hamza-aziz-ai/HalalLens/issues/131)) ([e2a3a99](https://github.com/hamza-aziz-ai/HalalLens/commit/e2a3a99a0875e5b0fd6c8529b9fc54dcb5dd0347))

## [0.3.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.2...v0.3.0) (2026-10-28)


### Features

* **deploy:** serve the dashboard and the API on one origin behind Caddy ([#128](https://github.com/hamza-aziz-ai/HalalLens/issues/128)) ([fda9a99](https://github.com/hamza-aziz-ai/HalalLens/commit/fda9a9986abe67ae6a8713984645d8d0b4f74342))


### Bug Fixes

* **config:** replace the developer LAN address defaults with portable ones ([#127](https://github.com/hamza-aziz-ai/HalalLens/issues/127)) ([1270ee9](https://github.com/hamza-aziz-ai/HalalLens/commit/1270ee9bac4f5fd706e69aeb7c5422ff73ccc234))

## [0.2.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.1...v0.2.2) (2026-10-28)


### Bug Fixes

* **ui:** drop the unwired GitHub Pages deployment and the LAN-address API fallback ([#123](https://github.com/hamza-aziz-ai/HalalLens/issues/123)) ([7ae29b7](https://github.com/hamza-aziz-ai/HalalLens/commit/7ae29b73f441107afb5b3334d43e4663fa813ec8))

## [0.2.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.0...v0.2.1) (2026-10-28)


### Bug Fixes

* **api:** take /alerts/check verdicts from stored evaluations and scope them to the caller ([#115](https://github.com/hamza-aziz-ai/HalalLens/issues/115)) ([6bee561](https://github.com/hamza-aziz-ai/HalalLens/commit/6bee561782d420f402a9529bbe6ecd8229a33d82))

## [0.2.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.1.1...v0.2.0) (2026-10-28)


### Features

* **jobs:** recompute stored evaluations from current stored inputs, dry run by default ([#91](https://github.com/hamza-aziz-ai/HalalLens/issues/91)) ([9d304ee](https://github.com/hamza-aziz-ai/HalalLens/commit/9d304eeec3b9dfc1764f6f02d2f78aade9a06069))

## [0.1.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.1.0...v0.1.1) (2026-10-28)


### Bug Fixes

* **narrator:** restore the optional LLM mode behind a best-effort consistency guard ([8c9dda2](https://github.com/hamza-aziz-ai/HalalLens/commit/8c9dda2d7a173c16a2cc9ef5e5f1a710171dc4bb))
* **ratio-engine:** stop partial data from passing the Shariah screen ([d048ca2](https://github.com/hamza-aziz-ai/HalalLens/commit/d048ca2e937f0d8efe321d21a28d8357f1a7c1a0))
* **ratio-engine:** stop partial data from passing the Shariah screen ([c359149](https://github.com/hamza-aziz-ai/HalalLens/commit/c359149ec5b3d65f6de29b0deb4b57ca79907e71))
