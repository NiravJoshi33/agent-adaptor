# OWS Hackathon - UI Theme Reference

> Extracted from [hackathon.openwallet.sh](https://hackathon.openwallet.sh/)
> Framework: **React + Mantine UI v7** (Vite build)

---

## Fonts

### Primary Font: Degular (Adobe Typekit)

- **Typekit Kit ID:** `obm6fsz`
- **Font Families:** `degular`, `degular-display`, `degular-text`, `degular-variable`
- **CSS Usage:** `font-family: degular-variable, degular, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif`
- **Weights Used:** 200 (Light/Italic), 300, 400, 500, 600, 700, 800
- **Key Usage:**
  - Title (hero): weight 200 italic + weight 800 bold combo
  - Body: weight 400
  - Headings: weight 700-800
  - Buttons: weight 600

### Monospace Font

- **CSS Variable:** `--mono`
- **Stack:** `ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Liberation Mono", Menlo, monospace`
- **Usage:** Countdown timers, labels, eyebrows, pill badges, schedule segments, prize amounts, pin codes, table headers, form inputs (letter-spacing: 0.3em, fontSize: 1.125rem)

### System Font (Mantine Default)

- **Stack:** `-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif, Apple Color Emoji, Segoe UI Emoji`
- Used as fallback for Mantine components

---

## Color Theme

### Custom CSS Variables (Light Mode)

| Variable          | Value                      | Usage                                             |
| ----------------- | -------------------------- | ------------------------------------------------- |
| `--text`          | `#111111`                  | Primary text                                      |
| `--text-2`        | `#444444`                  | Secondary text                                    |
| `--text-3`        | `#888888`                  | Tertiary/muted text                               |
| `--text-4`        | `#bbbbbb`                  | Quaternary/faded text, labels, eyebrows           |
| `--bg-card`       | `#ffffff`                  | Card backgrounds                                  |
| `--bg-input`      | `#f0ebe4`                  | Input field backgrounds (warm beige)              |
| `--accent-rose`   | `#d97059`                  | Accent color (countdown timer, links, highlights) |
| `--border`        | `rgba(0, 0, 0, 0.1)`       | Default borders                                   |
| `--border-mid`    | `rgba(0, 0, 0, 0.15)`      | Medium emphasis borders                           |
| `--border-strong` | `rgba(0, 0, 0, 0.22)`      | Strong borders (focus states)                     |
| `--node-active`   | `#1a1410`                  | Active node color (dark warm brown)               |
| `--node-demo`     | `#888888`                  | Demo node color                                   |
| `--track-fill`    | `#1a1410`                  | Track/progress fill (dark warm brown)             |
| `--mono`          | (see monospace font stack) | Monospace font variable                           |

### Background Blob Gradient

```css
--blob: radial-gradient(
  ellipse 900px 700px at 70% 100%,
  rgba(220, 165, 140, 0.38) 0%,
  rgba(235, 195, 175, 0.2) 45%,
  transparent 70%
);
```

A warm, peachy radial gradient used as a fixed background decoration.

### Footer Colors

| Element             | Value                       |
| ------------------- | --------------------------- |
| Footer background   | `#0a0a0a`                   |
| Column heading text | `#ffffff40` (25% white)     |
| Link text           | `#ffffff8c` (55% white)     |
| Link hover          | `#ffffffe6` (90% white)     |
| Copyright text      | `#fff3` (20% white)         |
| Footer border       | `rgba(255, 255, 255, 0.08)` |

### Pill/Badge Accent

```css
/* Default pill */
color: var(--text-2);
background: #0000000f;
border: 1px solid var(--border);

/* Accent pill */
color: var(--accent-rose);
background: #d9705914;
border-color: #d9705940;
```

### Success/Checkmark

```css
background: #dcfce7;
color: #16a34a;
```

---

## Typography Hierarchy

### Hero Title

```css
font-size: clamp(3.5rem, 7vw, 7rem);
line-height: 0.95;
letter-spacing: -0.04em;
color: var(--text);
/* Two-tone: light italic + bold */
.titleLight {
  font-weight: 200;
  font-style: italic;
}
.titleBold {
  font-weight: 800;
}
```

### Section Headings

```css
font-size: 2.5rem;
font-weight: 800;
color: var(--text);
letter-spacing: -0.04em;
line-height: 1.05;
/* Mobile: 1.875rem */
```

### Mantine Heading Scale

| Level | Font Size       | Font Weight | Line Height |
| ----- | --------------- | ----------- | ----------- |
| H1    | 2.125rem (34px) | 700         | 1.3         |
| H2    | 1.625rem (26px) | 700         | 1.35        |
| H3    | 1.375rem (22px) | 700         | 1.4         |
| H4    | 1.125rem (18px) | 700         | 1.45        |
| H5    | 1rem (16px)     | 700         | 1.5         |
| H6    | 0.875rem (14px) | 700         | 1.5         |

### Body/Font Sizes (Mantine Scale)

| Size | Value           |
| ---- | --------------- |
| `xs` | 0.75rem (12px)  |
| `sm` | 0.875rem (14px) |
| `md` | 1rem (16px)     |
| `lg` | 1.125rem (18px) |
| `xl` | 1.25rem (20px)  |

### Eyebrow Labels

```css
font-family: var(--mono);
font-size: 0.625rem; /* 10px */
letter-spacing: 0.14em;
text-transform: uppercase;
color: var(--text-4);
```

### Tagline/Description

```css
font-size: 1rem;
color: var(--text-2);
line-height: 1.6 - 1.75;
max-width: 480px;
```

### Sub/Caption Text

```css
font-size: 0.8125rem; /* 13px */
color: var(--text-4);
line-height: 1.6;
```

---

## Layout

### Container

```css
max-width: 1320px;
margin: 0 auto;
padding: 72px 48px 80px;
```

### Breakpoints (Mantine)

| Name | Value         |
| ---- | ------------- |
| `xs` | 36em (576px)  |
| `sm` | 48em (768px)  |
| `md` | 62em (992px)  |
| `lg` | 75em (1200px) |
| `xl` | 88em (1408px) |

### Custom Breakpoints Used

- `1000px` - Mobile apply button appears
- `900px` - Footer stacks vertically
- `768px` - Hub cards stack, heading shrinks
- `600px` - Tighter footer padding

### Spacing (Mantine Scale)

| Size | Value           |
| ---- | --------------- |
| `xs` | 0.625rem (10px) |
| `sm` | 0.75rem (12px)  |
| `md` | 1rem (16px)     |
| `lg` | 1.25rem (20px)  |
| `xl` | 2rem (32px)     |

### Grid Layouts

```css
/* Bottom section (content + form) */
grid-template-columns: 65fr 35fr;
gap: 60px;

/* Schedule lap bars */
grid-template-columns: 5fr 1fr 1fr;
gap: 3px;
height: 64px;

/* Hub selection grid */
grid-template-columns: 1fr 1fr;
gap: 6px;
```

### Base Line Height

```css
--mantine-line-height: 1.55;
```

---

## Animations

### fadeUp (Primary entrance animation)

```css
@keyframes fadeUp {
  0% {
    opacity: 0;
    transform: translateY(18px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}
/* Usage: 0.55s - 0.65s ease / cubic-bezier(.22,1,.36,1) */
/* Staggered delays: 0.1s, 0.18s, 0.28s, 0.36s, 0.45s, 0.55s */
```

### fadeIn

```css
@keyframes fadeIn {
  0% {
    opacity: 0;
  }
  100% {
    opacity: 1;
  }
}
/* Usage: 0.5s ease */
```

### segReveal (Schedule bar reveal)

```css
@keyframes segReveal {
  0% {
    clip-path: inset(0 100% 0 0);
  }
  100% {
    clip-path: inset(0 0% 0 0);
  }
}
/* Usage: 0.5s cubic-bezier(.4,0,.2,1) */
```

### blobDrift (Background animation)

```css
@keyframes blobDrift {
  /* Infinite floating/drifting motion */
  /* Duration: 18s ease-in-out infinite */
}
```

### hatchDrift (Build segment texture)

```css
@keyframes hatchDrift {
  0% {
    background-position: 0 0;
  }
  100% {
    background-position: 8px 8px;
  }
}
/* Duration: 4s linear infinite */
```

### shimmer (Build segment shimmer)

```css
@keyframes shimmer {
  0% {
    transform: translate(-120%);
  }
  100% {
    transform: translate(120%); /* implied */
  }
}
/* Duration: 0.7s ease forwards, delayed after segment reveal */
```

### marquee / marqueeReverse (Logo strips)

```css
@keyframes marquee {
  /* infinite horizontal scroll */
}
@keyframes marqueeReverse {
  /* reverse scroll */
}
/* Duration: 40s / 34s linear infinite */
/* Pauses on hover */
```

### nodePop

```css
@keyframes nodePop {
  0% {
    opacity: 0;
    transform: scale(0.4);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
```

### lapGrow

```css
@keyframes lapGrow {
  0% {
    transform: scaleX(0);
  }
  100% {
    transform: scaleX(1);
  }
}
```

### drawLine (Map connection line)

```css
@keyframes drawLine {
  0% {
    transform: translateY(-50%) translateY(-8px) scaleX(0);
  }
  100% {
    transform: translateY(-50%) translateY(-8px) scaleX(1);
  }
}
```

### outlineFade (Map US outline)

```css
@keyframes outlineFade {
  /* 1.2s ease, delay 0.3s */
}
```

### dashDraw (Map dashed connections)

```css
@keyframes dashDraw {
  /* 1.4s ease, delay 0.8s */
  stroke-dashoffset: 300 -> 0;
  stroke-dasharray: 4 5;
}
```

### finishRing

```css
@keyframes finishRing {
  0% {
    box-shadow: 0 0 #d9705973;
  }
  100% {
    box-shadow: 0 0 #d9705900;
  }
}
```

### Common Transitions

```css
transition: opacity 0.15s;
transition: color 0.15s;
transition:
  background 0.15s,
  border-color 0.15s;
transition:
  border-color 0.15s,
  background 0.15s,
  color 0.15s;
transition:
  box-shadow 0.2s,
  transform 0.2s;
transition:
  opacity 0.2s,
  transform 0.2s;
transition:
  transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
  box-shadow 0.22s ease,
  filter 0.22s ease;
```

---

## UI Components

### Header (Fixed)

```css
display: flex;
align-items: center;
justify-content: space-between;
padding: 16px max(48px, (100vw - 1320px) / 2 + 48px);
border-bottom: 1px solid var(--border);
position: fixed;
top: 0;
left: 0;
right: 0;
z-index: 100;
background: var(--bg);
/* Logo: height 48px */
```

### Primary Button (Submit/CTA)

```css
display: inline-flex;
align-items: center;
padding: 8px 16px;
background: var(--text); /* #111111 - dark */
color: #fff;
border-radius: 10px;
font-size: 0.9375rem;
font-weight: 600;
letter-spacing: -0.01em;
box-shadow: 0 1px 3px #0000001f;
transition:
  opacity 0.2s,
  transform 0.2s;
/* Hover: opacity 0.85, translateY(-1px) */
/* Active: translateY(0), opacity 1 */
```

### Secondary Button (GitHub/Outline)

```css
display: inline-flex;
align-items: center;
gap: 8px;
padding: 8px 16px;
background: #fff;
border: 1px solid rgba(0, 0, 0, 0.1);
border-radius: 10px;
font-size: 0.9375rem;
font-weight: 600;
color: var(--text);
box-shadow:
  0 1px 3px #0000000f,
  0 1px 2px #0000000a;
/* Hover: elevated shadow + translateY(-1px) */
```

### Full-Width Submit Button

```css
width: 100%;
height: 44px;
background: var(--text);
color: #fff;
font-size: 0.9375rem;
font-weight: 600;
border-radius: 4px;
letter-spacing: -0.01em;
/* Hover: opacity 0.82 */
/* Disabled: opacity 0.45, cursor not-allowed */
```

### Pill/Badge

```css
display: inline-block;
font-size: 0.6875rem;
font-family: var(--mono);
letter-spacing: 0.08em;
color: var(--text-2);
background: #0000000f;
border: 1px solid var(--border);
border-radius: 100px;
padding: 4px 12px;
```

### Cards

```css
/* General card styling */
border: 1px solid var(--border);
border-radius: 10px - 12px;
background: var(--bg-card); /* #ffffff */
box-shadow:
  0 2px 12px #0000000f,
  0 1px 3px #0000000a;
/* Hover: border-color transitions */
```

### Form Container

```css
box-shadow:
  0 2px 12px #0000000f,
  0 1px 3px #0000000a;
/* Focus-within: box-shadow 0 4px 24px #0000001a, 0 1px 4px #0000000d */
border-radius: 12px;
```

### Input Fields

```css
background: var(--bg-input); /* #f0ebe4 - warm beige */
font-family: var(--mono);
letter-spacing: 0.15em - 0.3em;
/* Focus: border-color var(--border-strong) */
```

### Hub Selection Option

```css
padding: 9px 12px;
border: 1px solid var(--border);
border-radius: 6px;
font-size: 0.8125rem;
font-weight: 500;
color: var(--text-2);
/* Selected: background var(--text), color #fff */
/* Hover: border-color var(--border-mid), background #00000008 */
```

### Footer

```css
background: #0a0a0a;
margin-top: 80px;
padding: 64px 48px 32px;
/* Footer nav: gap 64px */
/* Bottom bar: border-top 1px solid rgba(255,255,255,0.08) */
```

### Schedule Segments

```css
/* Build segment */
background-color: var(--track-fill); /* #1a1410 */
background-image: repeating-linear-gradient(
  45deg,
  rgba(255, 255, 255, 0.055) 0px,
  rgba(255, 255, 255, 0.055) 1px,
  transparent 1px,
  transparent 8px
);
border-radius: 3px;

/* Demo segment */
background: #0000001a;
border: 1px solid rgba(0, 0, 0, 0.08);

/* Labels on build: color #ffffffe6 */
/* Labels on demo: color #000 */
```

### Marquee/Logo Strip

```css
mask-image: linear-gradient(
  to right,
  transparent 0%,
  black 10%,
  black 90%,
  transparent 100%
);
/* Logos: height 32px, opacity 0.45, filter: brightness(0) */
/* Hover: opacity 0.85 */
```

---

## Box Shadows

| Usage          | Value                                       |
| -------------- | ------------------------------------------- |
| Subtle         | `0 1px 3px #0000000f`                       |
| Button default | `0 1px 3px #0000001f`                       |
| Elevated       | `0 1px 3px #0000000f, 0 1px 2px #0000000a`  |
| Card           | `0 2px 12px #0000000f, 0 1px 3px #0000000a` |
| Hover elevated | `0 4px 14px #00000014, 0 1px 3px #0000000d` |
| Button hover   | `0 4px 14px #0000001f, 0 1px 4px #0000000f` |
| Focus form     | `0 4px 24px #0000001a, 0 1px 4px #0000000d` |
| Segment hover  | `0 8px 20px #00000038`                      |
| Focus ring     | `0 0 0 3px #0000000f`                       |

---

## Design Aesthetic Summary

- **Style:** Minimal, editorial, warm
- **Vibe:** Clean and professional with warm, understated tones -- not cold/tech-blue
- **Background:** Off-white/cream with a warm peachy radial blob gradient (fixed, drifting)
- **Color Palette:** Near-black text (#111), grays (#444, #888, #bbb), warm rose accent (#d97059), white cards
- **Typography:** Degular (geometric sans-serif by OH no Type Co) with monospace for technical elements
- **Layout:** Max 1320px centered, generous whitespace, 2-column bottom grid (65/35)
- **Interactions:** Subtle lift on hover (-1px translateY), gentle opacity transitions (0.15s-0.2s)
- **Visual Texture:** Hatched line pattern on schedule bars, shimmer effects, dashed borders for breaks
- **Animation Style:** Staggered fade-up entrances with cubic-bezier easing, clip-path reveals for schedule bars
- **Border Approach:** Thin (1px), low-opacity black borders; accent borders use rose tones
- **Dark Elements:** Footer (#0a0a0a), CTAs use near-black backgrounds
- **Map Feature:** SVG US outline with animated dash-drawn connection lines between hub cities
- **Form Style:** Warm beige inputs (#f0ebe4), monospace letter-spaced text, 4px border-radius
- **Overall Feel:** Hackathon energy meets editorial calm -- technical but approachable
