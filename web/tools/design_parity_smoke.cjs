// Compatibility entry point: current unified visual acceptance, no synthetic business writes.
if (process.argv.includes('--before')) throw new Error('Historical before-snapshots are preserved in web-design-parity-20261027; use commit64c0213 for the old shell.');
process.argv.push('--visual');
require('./unified_workspace_smoke.cjs');
