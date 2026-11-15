# Adding reviewed terrain coverage

Only Site01 currently has a reviewed, registered mask. Site04 and Site23 already have verified observer ephemerides, but their terrain remains unavailable until the GIS teammate supplies reviewed masks. The handoff checker and multi-site integration tests prepare the backend for those files; they do not create new scientific coverage.

## Deployment requirements

The existing deployment has two services: the FastAPI Docker API and the Next.js web app (configured for Render and Vercel in [the deployment guide](deploy.md)). Deploy the API image first and set `LUNARWINDOW_CORS_ORIGINS` to the web origin. Build the web app with `NEXT_PUBLIC_API_BASE_URL` pointing to the API's HTTPS URL. A changed public API URL requires a web rebuild.

For precomputed masks, the API image needs the reference ephemerides, registered mask JSON files, and its verified saved-result release. It needs no source DEM rasters, GIS extras, database, Strapi instance, or runtime NASA access. GIS generation happens separately using the original DEMs. No hosting changes or deployment credentials are needed to prepare or check a handoff locally.

The image build and CI check **every** registered mask against its archive. After deployment, `/api/ready` must succeed and `/api/reference/sites` must advertise the expected reviewed mask IDs and checksums. The frontend already reads terrain availability from that catalog; adding a compatible registered mask does not require a new toggle or response shape.

## Request to the GIS teammate

> Please prepare reviewed `lunarwindow.terrain-mask.v1` JSON files for `lola-site04-reference` (Shackleton inner wall) and `lola-site23-reference` (Malapert massif). Match each observer in `data/reference/validation-30d/<site-id>.json`, including its 0 m mast and altitude above the 1737.4 km sphere. Send the Git branch, exact artifact paths, and separately communicated trusted SHA-256 checksums. Beside the files, include review notes covering DEM URLs/checksums, generation command and clean Git revision, coverage and missing-data checks, reproducibility, observer-height sensitivity, and scientific limits. Declare DE421 MOON_ME and any transformation applied; the backend retains explicit acceptance of the Horizons Mean Earth approximation. Label unreviewed results preliminary. A different mast height also needs matching ephemerides.

The current observer requirements come from the archived datasets and `data/reference/site-provenance.json`:

| Site                          | Latitude (degrees) | East longitude (degrees) | Total altitude (km) | Mast (m) |
| ----------------------------- | -----------------: | -----------------------: | ------------------: | -------: |
| Site04, Shackleton inner wall | -89.76674147712977 |      -171.89280908299654 |  0.7679786376953125 |        0 |
| Site23, Malapert massif       | -85.99486736492491 |     -0.23460969154338968 |    4.78362939453125 |        0 |

Use the original JSON numeric values when generating, rather than rounded display coordinates. Site04 is an inner-wall reference point, not a rim landing target. The archived observers are DEM reference points, not certified landing sites.

The expected full ephemeris JSON hashes are:

- Site04: `fa9b4e639709be80d49274895aaff003da8233e2b5644de67d372e43e3cee470`.
- Site23: `d6b6e13763f9ce645d87744f872ab754944c4fa87c2027c52b1bc0c2f28698aa`.

The original 5 m tile hashes recorded with those observers are:

- Site04: `38ff70dbdf2f066c2cfa94a646c3a59d653ce7f6b4528b15fc1b43ee397ce758`.
- Site23: `12d280a59cd7580415f6bada638d0abe025ce6727541fddf68d5dc371a6c94cf`.

The current GIS exporter/product catalog configures the Site01 fine tile. The GIS producer must configure the matching Site04/Site23 source tiles before exporting those sites; changing `--site-id` alone is insufficient. See [the GIS work package](terrain-gis-lead.md) for the ray caster, source acquisition, and review limits. Preliminary `lunarwindow.horizon.v1` profiles are a different contract and cannot be registered as `TerrainMask` files.

## Check a candidate offline

Install the backend with `python -m pip install -e './backend[dev]'`. No GIS extra is needed to validate a supplied JSON mask. For an incoming Site04 file, substitute the actual path and checksum supplied by its reviewer:

```sh
python -m lunarwindow.terrain.handoff candidate /path/to/site04-mask.json \
  --site-id lola-site04-reference \
  --expected-sha256 <trusted-sha256> \
  --reference-dir data/reference/validation-30d \
  --allow-mean-earth-approximation
```

Repeat for Site23 using its site ID and checksum. The installed `lunarwindow-terrain-handoff` command accepts the same arguments. A candidate does not have to be registered already.

The command checks the exact supplied bytes against the trusted checksum, validates `TerrainMask`, rejects a different expected site, verifies the entire reference archive, and checks observer coordinates, height, sphere, dates, frame declarations, and refraction. It returns a `lunarwindow.terrain-handoff.v1` JSON report with `status: "compatible"`, original observer/frame/DEM/algorithm metadata, the full ephemeris artifact hash and availability, and the explicit compatibility assessment. Failures return a nonzero exit code, diagnostic text on stderr, and no success JSON. Invalid arguments return argparse's exit code 2.

It reads no checksum sidecars and does not write files, download DEMs, regenerate horizons, calculate visibility, or register a mask. The default rejects the supported frame pairing; the flag explicitly permits the documented approximate pairing **for this check** and never changes API caller requirements. A compatible report establishes neither scientific review nor independent validation of the claimed DEM hashes or individual terrain events. Those checks remain part of the GIS handoff.

## Integrate after GIS review

1. Review the evidence and checker report. Preserve the received artifact bytes; formatting changes its checksum.
2. Add the JSON and README under `data/reference/terrain-masks/` and pin `(site_id, filename, trusted_sha256)` under the mask ID in `backend/src/lunarwindow/terrain/registry.py`. Requests and adjacent sidecars never select the trusted hash. Do not add an unavailable or preliminary mask to the registry.
3. Check every registration:

   ```sh
   python -m lunarwindow.terrain.handoff registered \
     --reference-dir data/reference/validation-30d \
     --terrain-dir data/reference/terrain-masks \
     --allow-mean-earth-approximation
   ```

   This also rejects registrations whose sites are absent from the archive. It returns the list of compatible reports under `masks` (`lunarwindow.terrain-handoffs.v1`) only if all pass.

4. Add scientific regression baselines derived from the actual new masks, with review of blocking, negative horizons, interpolation, windows, and provenance. The new `test_multisite_terrain.py` uses explicitly synthetic high/low horizons to exercise integration; it is not a Site04/Site23 scientific baseline.
5. If the new cases need saved full-month results, create a **new** pending release plan pinning their actual archive and mask hashes, build and replay it with the [release workflow](data-releases.md), and update the packaged release selection and expected job counts together. Do not modify the published v1 release. Live evaluation can serve a newly registered site even without an exact saved result.
6. Run backend tests, rebuild the API image, and verify readiness, catalog metadata, and a terrain evaluation per new site with explicit frame acceptance. Check that cross-site mask requests and omitted acceptance return 422. Deploy the API, then verify the existing frontend enables terrain only for the advertised sites.

Changing mast height or observer coordinates requires a matching reviewed mask and ephemeris archive. A 2 m mast changed the existing Site01 horizon by up to 1.9 degrees; that measured sensitivity must not be assumed to describe the other sites.
