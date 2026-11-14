# Demo script (about 2 minutes)

Every number below comes from the archived NASA data the app ships with. They reproduce exactly in a clean browser, locally (`docker compose up --build -d --wait`) or on the deployed site. Wake the hosted API a few minutes before recording (see `docs/deploy.md`).

## 1. The question (15 s)

> "At the lunar south pole, the Sun skims the horizon and Earth bobs up and down. A lander needs both: the Sun for power and Earth for a direct radio link. LunarWindow answers when you get both, at a given site and date."

Show the top of the page and the data banner: archived JPL Horizons ephemerides, the available period (14 Nov to 14 Dec 2026), and **"Geometric: flat 0° horizon"**.

## 2. The schedule slip (45 s)

The archive covers 30 days, so the slip shown is about two weeks rather than six.

1. **Scenario A:** Connecting ridge (Site01), **17–24 Nov**. Press **Update comparison**.
   - Sun visible 100%, Earth visible **95%**.
   - Longest simultaneous operation: **≥ 160 h**. The "≥" means the window is still open when the period ends.
2. **Scenario B:** the same site, **1–8 Dec**. Press **Update comparison**.
   - The Sun is still up 100% of the time, but Earth visible drops to **0%**.
   - Longest communication outage: **≥ 168 h**, the whole week.

> "Same site, two weeks later: plenty of power, and no direct link to Earth for the entire stay."

## 3. Find another option (30 s)

1. Switch scenario B to **Malapert massif**, still 1–8 Dec, and update.
   - Sun 42%, Earth 36%.
   - The **Mission window finder** lists a combined Sun + Earth window of **≥ 61 h** at the start of the week.
2. Press **Show**: the shared cursor jumps to that window on the timeline.

## 4. Why: the sky (20 s)

Scroll to the **Lunar sky explorer**, scenario A.

> "Earth's track is a small loop near 136° azimuth, because of libration. When the loop dips below the horizon, the link is gone. The Sun circles the whole sky once a month, only a couple of degrees up."

Drag the timeline cursor and watch the markers move.

## 5. Honesty (10 s)

> "These results use a flat horizon. We computed a validated LOLA terrain horizon for one site, and integrating it is the next step. The QuickMap cross-checks validate our Sun and Earth angles for observers about 100 km up, not ground-level shadows."
