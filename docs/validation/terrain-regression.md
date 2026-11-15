# Terrain-aware backend regression evidence

These checks verify the implemented software model. The Site01 baseline is an independent calculation of the same interpolation, disc, and sample-and-hold rules; it is not independent terrain-observation validation. It does not certify sunrise times, a lander site, solar power, or a radio link. The frame approximation, 0 m mast, and near-field limitations of the [reviewed mask](../../data/reference/terrain-masks/README.md) remain in effect.

## Fixed inputs and expected outputs

The committed expectations are in [site01-terrain-regression.json](../../backend/tests/fixtures/site01-terrain-regression.json). They use the reviewed Site01 observer and the archived interval `[2026-11-14T00:00:00Z, 2026-12-14T00:00:00Z)`, with 720 hourly observations and countdowns relative to the start.

| Input                                                             | SHA-256                                                            |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| `data/reference/terrain-masks/lola-site01-reference-mast-0m.json` | `4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d` |
| `data/reference/validation-30d/lola-site01-reference.json`        | `519628d7384992cc012039fe9df226a932d6c482de56b0b3277fdff6f30e9b50` |

Selected model totals, in hours:

| Mode      | Visibility rule | Sun | Earth | Both | Longest darkness |
| --------- | --------------- | --: | ----: | ---: | ---------------: |
| Geometric | any-disc        | 720 |   312 |  312 |                0 |
| Geometric | body-center     | 720 |   283 |  283 |                0 |
| Geometric | full-disc       | 720 |   252 |  252 |                0 |
| Terrain   | any-disc        | 442 |   232 |   81 |              278 |
| Terrain   | body-center     | 427 |   199 |   60 |              293 |
| Terrain   | full-disc       | 394 |   162 |   27 |              316 |

The fixture also records all five window categories with exact UTC boundaries and truncation flags, percentages, longest intervals, setting brackets/countdowns, disc-state counts, and horizon-elevation checkpoints. These are fixed model expectations for these source bytes and rules, not observed illumination/contact durations.

## Independent derivation

[build_terrain_regression.py](../../scripts/build_terrain_regression.py) has no production package imports or API calls. It checks both input hashes, then:

1. Computes circular horizon interpolation using 50-digit decimal arithmetic and cross-checks it with NumPy's periodic interpolation.
2. Uses each archived body's elevation `e` and angular radius `r` against its interpolated horizon `h`: any-disc requires `e + r > h`, body-center requires `e > h`, and full-disc requires `e - r >= h`.
3. Groups the resulting hourly flags with `itertools.groupby` to obtain interval boundaries. Durations follow the fixed hourly grid; percentages use rational counts rather than summing the production engine's floating weights.
4. Derives setting brackets from observed ends of visible runs. No sub-hour crossing time or event at the archive end is invented.

The generator records the smallest absolute threshold clearances. They exceed the regression's numerical tolerance, so the real baseline is separated from floating-point tangencies. Exact tangency semantics are checked with synthetic cases instead.

Tests never regenerate the fixture or obtain expected results by calling the production engine. Regeneration is explicit, and source or model changes require reviewing the expected-results diff:

```sh
python scripts/build_terrain_regression.py --output data/processed/site01-terrain-regression.candidate.json
git diff --no-index backend/tests/fixtures/site01-terrain-regression.json data/processed/site01-terrain-regression.candidate.json
```

Both input hashes are pinned in the generator too. Review the source change before updating those pins or replacing the committed baseline. The source mask and ephemeris artifacts are never rewritten by this utility.

## Regression coverage

[test_terrain_regression.py](../../backend/tests/test_terrain_regression.py) contains two layers:

- **Hand-calculated synthetic cases.** Constant, positive body elevations pass through open and blocked azimuth sectors. The expected Sun/Earth flags and all windows are written explicitly, including a half-hour final interval. Separate cases check setting brackets and cursor changes, the 359-to-0 seam, a negative horizon that reveals Earth below local horizontal, partial discs, and upper/lower-limb tangencies for all three rules. These synthetic examples exist only in tests.
- **Real-input API model baselines.** All six mode/rule combinations must match the fixed metrics, windows, every visibility flag/disc state, and numerical checkpoints. Geometric v1 stays flat. Terrain v2 must preserve the original mask, checksum, observer, NASA ephemeris values/provenance, approximate frame policy, source references, and limitations. The original artifact bytes must remain unchanged.

The HTTP integration tests additionally cover checksum failures, missing artifacts, unknown IDs, strict frame-policy rejection, incompatible site pairings, and geometric independence. Existing contract and engine tests cover invalid inputs and time-grid constraints. The new checks found no production behavior that needed changing.

Run offline:

```sh
python -m unittest discover -s backend/tests -p test_terrain_regression.py -v
python -m unittest discover -s backend/tests -v
docker compose run --build --rm ephemeris-test
```

Scientific validation against surface imagery or an independent terrain-visibility dataset remains separate work. The existing QuickMap camera comparisons check body pointing at elevated observers; they do not validate this ground-level terrain mask.

## Surface scientific comparisons

The [surface SPICE comparison and terrain-evidence audit](surface-science.md) now cover all three archived surface observers and all 720 hourly samples, with a separately generated NAIF reference. Shared-mask model consistency is reported separately; independent dated terrain evidence remains pending.
