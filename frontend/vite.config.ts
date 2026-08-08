import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { federation } from '@module-federation/vite'
import pkg from './package.json' with { type: 'json' }

/**
 * Two build shapes out of one config:
 *
 *   vite build                  → dist/         standalone dev harness (src/dev), NOT shipped
 *   vite build --mode remote    → dist-remote/  the Module Federation remote (src/index.ts)
 *
 * Only the `remote` output is a deliverable. See INTEGRATION.md.
 */
export default defineConfig(({ mode }) => {
  const isRemote = mode === 'remote'
  const isCheck = mode === 'check'

  return {
    plugins: [
      vue(),
      ...(isRemote
        ? [
            federation({
              name: 'wpBoard',
              filename: 'remoteEntry.js',
              // The automatic .d.ts generator shells out to plain `tsc`, which cannot read
              // `.vue` SFCs, so it fails on every build. The exposed surface is small and
              // stable, so it is declared by hand in `types/wpBoard.d.ts` instead.
              dts: false,
              exposes: {
                // Four entries, one per host menu item (`plan.md` §0.1 / §0.5-3 / §0.6-4,
                // INTEGRATION.md §5). Separate modules rather than one barrel so a host that
                // only mounts the project workspace never loads the admin screens — and so
                // the two screens with no grid never drag ag-grid in with them.
                './MasterAdmin': './src/entries/masterAdmin.ts',
                './ProjectWorkspace': './src/entries/projectWorkspace.ts',
                './ProjectsOverview': './src/entries/projectsOverview.ts',
                './MakerSettings': './src/entries/makerSettings.ts',
              },
              // Anything the host is likely to already have must be a singleton, or we
              // end up with two Vues (broken injection) / two ag-grid module registries.
              shared: {
                vue: { singleton: true, requiredVersion: pkg.dependencies.vue },
                'ant-design-vue': {
                  singleton: true,
                  requiredVersion: pkg.dependencies['ant-design-vue'],
                },
                'ag-grid-community': {
                  singleton: true,
                  requiredVersion: pkg.dependencies['ag-grid-community'],
                },
                'ag-grid-vue3': {
                  singleton: true,
                  requiredVersion: pkg.dependencies['ag-grid-vue3'],
                },
                dayjs: { singleton: true, requiredVersion: pkg.dependencies.dayjs },
              },
            }),
          ]
        : []),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    ssr: {
      // Only used by `npm run check:dom`. antd's `es/` build has extensionless deep
      // imports that Node's ESM resolver rejects, so it has to be bundled rather than
      // externalised. No effect on either shipped build.
      noExternal: ['ant-design-vue', 'ag-grid-community', 'ag-grid-vue3', '@ant-design/icons-vue'],
    },
    server: {
      port: 5180,
      proxy: {
        // Dev harness convenience only; the shipped remote never assumes a proxy.
        '/api': {
          target: process.env.WP_DEV_API_TARGET ?? 'http://localhost:8010',
          changeOrigin: true,
        },
      },
    },
    build: isCheck
      ? {
          // `npm run check:dom`: a *client*-compiled bundle that happens to run under
          // Node against jsdom. It must not be a `--ssr` build — that emits `ssrRender`
          // functions, which cannot be mounted. `vue` and `@vue/test-utils` stay external
          // so the harness and the component share one Vue instance.
          outDir: 'dist-check',
          emptyOutDir: true,
          minify: false,
          target: 'node20',
          lib: {
            entry: fileURLToPath(new URL('./src/dev/domCheck.ts', import.meta.url)),
            formats: ['es'],
            fileName: () => 'domCheck.mjs',
          },
          rollupOptions: {
            external: [/^node:/, 'jsdom', '@vue/test-utils', 'vue'],
          },
        }
      : isRemote
      ? {
          outDir: 'dist-remote',
          target: 'chrome89',
          cssCodeSplit: false,
          minify: true,
          rollupOptions: {
            input: [
              fileURLToPath(new URL('./src/entries/masterAdmin.ts', import.meta.url)),
              fileURLToPath(new URL('./src/entries/projectWorkspace.ts', import.meta.url)),
              fileURLToPath(new URL('./src/entries/projectsOverview.ts', import.meta.url)),
              fileURLToPath(new URL('./src/entries/makerSettings.ts', import.meta.url)),
            ],
          },
        }
      : {
          outDir: 'dist',
          target: 'es2022',
        },
  }
})
