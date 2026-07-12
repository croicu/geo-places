# geo-places

[![CI](https://github.com/croicu/geo-places/actions/workflows/ci.yaml/badge.svg)](https://github.com/croicu/geo-places/actions/workflows/ci.yaml)
[![CD](https://github.com/croicu/geo-places/actions/workflows/cd.yaml/badge.svg)](https://github.com/croicu/geo-places/actions/workflows/cd.yaml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Static data repository for [geo-browser](https://github.com/croicu/geo-browser)'s map layers. No app, no rendering — just hand-authored area manifests in, deploy-ready GeoJSON out.

**Live:** [geo-places.croicu.com](https://geo-places.croicu.com)

## What this is

Each area (a city or region) is described by a small manifest: a bounding box and a set of layers — parks, water, buildings, whatever's worth drawing — each backed by an [Overpass](https://overpass-api.de/) query. The [`geo-builder`](https://github.com/croicu/geo-builder) CLI reads those manifests, pulls the matching OpenStreetMap data, and writes deploy-ready GeoJSON. This repo holds the manifests; the built output is never committed — it's generated fresh on every deploy and pushed straight to Cloudflare Pages.

```text
public/catalog.json + public/areas/*/manifest.json   (hand-authored: bbox, layers, filters)
        │
        ▼
   geo-builder CLI  ──▶  Overpass API
        │
        ▼
out/catalog.json + out/areas/*/manifest.json + out/areas/*/layers/*.geojson
        │
        ▼
 wrangler pages deploy  ──▶  Cloudflare Pages  ──▶  geo-places.croicu.com
```

`geo-browser` only ever fetches these static files — it never talks to Overpass directly.

## Areas

| Area | Region |
|---|---|
| Prague | Czechia |
| Berlin | Germany |
| Algarve | Portugal |
| Stockholm | Sweden |
| Seattle | USA |

## Building locally

```bash
pip install git+https://github.com/croicu/geo-builder.git@v1.0.0

./build.sh          # build.cmd on Windows — writes deploy-ready output to out/
npm run dev          # serve out/ on http://localhost:5174 for a local geo-browser to fetch from
```

## Contributing

Adding or editing an area means hand-editing `public/catalog.json` and `public/areas/<id>/manifest.json` — see [`CLAUDE.md`](CLAUDE.md) for the full schema, architecture rules, and CI/CD setup.

## License

[MIT](LICENSE)
