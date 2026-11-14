# Challenge interpretation

Source: [Lunar Landing Site Navigator — NASA Space Apps 2026](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/), reviewed November 13, 2026.

## Problem and audience

Changes in landing location or schedule can change the lighting and Earth visibility available to a lunar mission. Existing scientific tools expose useful data but make rapid comparison difficult. The challenge asks for an intuitive comparison tool for mission planners, educators, and the public, with particular attention to the south pole.

## Proposed MVP

These are project implementation choices based on the challenge's suggested capabilities, not additional NASA requirements.

| Capability                   | Proposed implementation                                                     | Scaffold status                   |
| ---------------------------- | --------------------------------------------------------------------------- | --------------------------------- |
| Compare locations            | Two independent scenarios; custom coordinates first, verified presets later | Editable input shell              |
| Compare schedules            | UTC start/end dates and sampling interval per scenario                      | Input validation ready            |
| Inspect local sky            | Sun/Earth azimuth and elevation relative to the horizon                     | Data contract ready; view pending |
| Explore changes over time    | Timeline and elevation plots                                                | Pending                           |
| Assess sunlight availability | Duration, next sunset, longest darkness                                     | Pending                           |
| Assess Earth visibility      | Visibility periods, next Earthset, longest blackout                         | Pending                           |
| Understand results           | Units, plain-language explanations, sources, model assumptions              | Documentation started             |

## Scientific scope

Start with airless Sun/Earth center positions above a mathematical local horizontal plane. Later add terrain horizon profiles from LOLA DEMs. Terrain can substantially change polar visibility, so results must always identify the model used.

Sun visibility is an input to a power assessment; electrical output also depends on array orientation, efficiency, and hardware. Earth visibility is an initial geometric communication proxy; ground-station locations and antenna/link constraints require further work. The Python ephemeris module exports real apparent Sun/Earth center angles. A separate visibility engine now calculates disc states, metrics, windows, and setting brackets from supplied angles and a horizon profile; the HTTP provider currently supplies synthetic inputs. Real terrain integration, electrical power, and radio-link models remain pending. See [the visibility model](visibility.md).

## Later enhancements

Terrain-aware horizons, 3D surface views, curated historic/CLPS sites, animated time controls, accessible explanatory modes, and shareable or exportable comparisons. Add them after the core data path is verified.
