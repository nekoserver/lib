import type { TargetEnv } from './transport';
export interface Env extends TargetEnv {
  THIN_CLIENT_TOKEN: string;
  TAILSCALE_WASM_AUTHKEY?: string;
  TAILNET: DurableObjectNamespace;
  JOBS: DurableObjectNamespace;
}
declare module '*.wasm' { const module: WebAssembly.Module; export default module; }
