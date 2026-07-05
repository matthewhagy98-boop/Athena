---
name: Scholastic Precision
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#45464d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#006a61'
  on-secondary: '#ffffff'
  secondary-container: '#86f2e4'
  on-secondary-container: '#006f66'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#0b1c30'
  on-tertiary-container: '#75859d'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#89f5e7'
  secondary-fixed-dim: '#6bd8cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#005049'
  tertiary-fixed: '#d3e4fe'
  tertiary-fixed-dim: '#b7c8e1'
  on-tertiary-fixed: '#0b1c30'
  on-tertiary-fixed-variant: '#38485d'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Source Serif 4
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 30px
  body-md:
    fontFamily: Source Serif 4
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
  max-width-content: 1200px
---

## Brand & Style

The brand identity centers on **Academic Authority** and **Computational Precision**. It is designed for a target audience of research scientists, data analysts, and policy makers who require high information density without cognitive fatigue. The UI evokes the "Flow State" of deep work—quiet, focused, and intellectually stimulating.

The design style is a **Refined Corporate Modernism** with **Minimalist** leanings. It avoids unnecessary decoration, relying instead on structural alignment, intentional whitespace, and superior typography to communicate value. The aesthetic mimics the clarity of a high-end scientific journal while utilizing the interactive speed of modern AI-driven tools.

## Colors

This design system utilizes a high-contrast professional palette to establish hierarchy and focus.

*   **Primary (Deep Navy):** Used for core navigation, headings, and foundational UI elements to project stability and institutional trust.
*   **Secondary (Teal Accent):** A crisp teal used exclusively for primary actions, success states, and indicating AI-generated insights. It provides a sharp visual contrast against the navy and slate.
*   **Neutral (Slate Grays):** A tiered scale of grays used for secondary text, borders, and metadata.
*   **Backgrounds:** A very light cool gray (`#F8FAFC`) serves as the base canvas to reduce eye strain compared to pure white, with pure white reserved for "elevated" content cards.

## Typography

The typography strategy employs a dual-font system to distinguish between **Functional UI** and **Intellectual Content**.

*   **Inter (Sans-Serif):** Used for the interface, navigation, buttons, and data labels. Its neutral, systematic nature ensures that the "tool" remains unobtrusive.
*   **Source Serif 4 (Serif):** Used for long-form research summaries, paper abstracts, and editorial content. The serif terminals assist the eye in tracking across long lines of dense text, providing a literary quality that honors the source material.

**Hierarchy Rules:**
- Use `headline-xl` for page titles and major section headers.
- Use `body-lg` for primary research synthesis to encourage deep reading.
- Use `label-md` with uppercase styling for table headers and metadata categories to create a clear visual distinction from narrative text.

## Layout & Spacing

The layout follows a **Fixed-Fluid Hybrid** model. The main content container is capped at 1200px for optimal readability, centered on the screen with generous margins.

*   **Grid System:** A 12-column grid is used for desktop. Research papers and data visualizations should typically span 8 columns, with a 4-column sidebar for citations, related metrics, and AI tools.
*   **Vertical Rhythm:** Based on a 4px baseline grid. Components should use increments of 8px for padding and margins (8, 16, 24, 32, 48, 64) to maintain a rigorous, structured feel.
*   **Responsive Behavior:** 
    *   **Desktop:** 12 columns, 48px margins. 
    *   **Tablet:** 8 columns, 32px margins. 
    *   **Mobile:** 4 columns, 16px margins; sidebars collapse into bottom-sheet drawers or stack vertically.

## Elevation & Depth

Depth is communicated through **Tonal Layers** and **Low-Contrast Outlines** rather than heavy shadows. This maintains a flat, scholarly aesthetic.

*   **Surface Tiers:** The base background is `#F8FAFC`. Content containers (cards) use pure white backgrounds with a subtle 1px border in `#E2E8F0`.
*   **Interaction Depth:** Only the primary active element or a "focused" research card should receive a shadow. When used, shadows must be ambient: `0 4px 12px rgba(15, 23, 42, 0.05)`, creating a very slight lift without appearing "gamey."
*   **Dividers:** Use hairline dividers (`1px`) in `#F1F5F9` to separate rows in data tables or bibliography lists.

## Shapes

The shape language is **Soft (0.25rem)**. This subtle rounding prevents the interface from feeling sharp or aggressive while maintaining a disciplined, professional structure.

*   **Buttons & Inputs:** Use the standard `rounded` (4px) radius.
*   **Cards & Modals:** Use `rounded-lg` (8px) to provide a gentle container for dense data.
*   **Data Indicators:** For "Evidence Strength" bars or "Citation Tags," use the same 4px radius. Avoid pill shapes unless used for status indicators (e.g., "Published" vs "Pre-print").

## Components

### Buttons & Actions
- **Primary:** Deep Navy background with White text. For critical "Action" buttons like "Run Analysis" or "Export," use the Teal accent.
- **Secondary:** Ghost style with a 1px Slate-300 border and Navy text.
- **Iconography:** Use 20px line icons with a consistent 1.5px stroke weight.

### Cards & Data Visualization
- **Research Cards:** White background, 1px Slate-200 border, 8px padding. Title in Inter (Bold), Summary in Source Serif 4.
- **Evidence Indicators:** Use a 5-step horizontal bar chart using the Teal accent to represent confidence levels.

### Input Fields
- Inputs should be minimalist: a 1px border on all sides that turns Teal on focus. Labels should always be visible in `label-sm` style.

### Navigation
- **Sidebar:** A collapsed or slim sidebar in Deep Navy with Teal active indicators. This maximizes horizontal space for data tables and research text.

### Lists & Citations
- Citation lists should use `body-sm` (Inter) to maximize density. Links should be underlined in Teal only on hover to maintain a clean reading environment.