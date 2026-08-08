import { createApp } from 'vue'
import DevHarness from './DevHarness.vue'
import './host.css'

/**
 * Dev harness bootstrap. This is the ONLY `createApp` in the package — the shipped
 * artefact exposes a component, not an application (INTEGRATION.md §5).
 */
createApp(DevHarness).mount('#app')
