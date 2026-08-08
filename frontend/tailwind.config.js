/**
 * Tailwind is deliberately constrained so this package can be loaded into a host
 * application without touching anything the host owns. See INTEGRATION.md §5.
 *
 *  - `corePlugins.preflight: false` — no global element reset. Preflight rewrites
 *    `*`, `html`, `body`, `h1..h6`, `button`, `img`… and is the single most common
 *    way a federated remote destroys its host's styling.
 *  - `prefix: 'wp-'` — every generated utility is namespaced (`wp-flex`, not `flex`),
 *    so even if the host also ships Tailwind the two rule sets cannot collide.
 *  - `content` is scoped to this package only. Never widen it to `../`.
 *  - `important: '.wp-root'` is intentionally NOT set: raising specificity would make
 *    our utilities win over host styles on shared elements. We only style our own tree.
 */
/** @type {import('tailwindcss').Config} */
export default {
  prefix: 'wp-',
  corePlugins: {
    preflight: false,
  },
  content: ['./index.html', './src/**/*.{vue,ts,tsx,js,jsx}'],
  theme: {
    extend: {
      fontSize: {
        '2xs': ['11px', '15px'],
      },
    },
  },
  plugins: [],
}
