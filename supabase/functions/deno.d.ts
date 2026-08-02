// Ambient type declarations for Deno runtime and URL imports in IDE TypeScript service
declare module "https://*" {
  const content: any;
  export default content;
  export const serve: any;
  export const createClient: any;
  export const computeCanonicalHash: any;
  export const isValidHexSha256: any;
  export const authenticateWorker: any;
  export const AuthenticationError: any;
  export const sha256Hex: any;
  export const hmacSha256Hex: any;
  export const timingSafeEqual: any;
}

declare namespace Deno {
  export namespace env {
    export function get(key: string): string | undefined;
    export function set(key: string, value: string): void;
  }
}
