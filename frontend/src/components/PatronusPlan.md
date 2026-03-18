## Stag Opening Animation Plan

### Goal
Replace the grid-based AnimeJS opening animation with a highly detailed, animated "neuron web" Stag. The Stag should glow silvery-white-blue (like a Patronus) to visually represent the new Semantic Memory model. It needs ambient movement and connections representing a neural network model.

### Technical Approach
Since we only have vanilla CSS and React (without heavy 3D libraries like Three.js), building a fully 3D volumetric stag from scratch is out of scope. However, we can achieve an incredible glowing string-art/constellation effect using the **HTML5 Canvas API**.

1.  **Canvas Particles:** I will create a React component (`PatronusStag.tsx`) that mounts a full-screen `<canvas>`.
2.  **Stag Geometry:** I will define the approximate 2D shape of a stag (body, antlers, legs) using a set of anchor points.
3.  **Neuron Web (Boids/Springs):**
    *   Initialize hundreds of "neuron" particles that gravitate toward the Stag's anchor points.
    *   Draw glowing, silvery-blue lines (`ctx.beginPath()`) between particles that are close to each other, creating the "web/network" look.
4.  **Ambient Movement:**
    *   Apply a gentle sine-wave oscillation to the points so the Stag breathes/shimmers.
    *   Make the particles react slightly to mouse movement.
5.  **Glow Effect:**
    *   Use Canvas `shadowBlur` and `shadowColor` (`#e0f2fe`, `#38bdf8`) to create the Patronus ethereal glow.
6.  **Transition:** After a few seconds, or on click, the Stag dissolves into particles that fly off-screen, revealing the `AgentInterface`.

This approach fits perfectly within the React/Vite stack without adding massive external dependencies, while delivering the exact "neural web glowing Patronus" vibe requested.
