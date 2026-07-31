/// <reference types="vite/client" />

export {};

declare module "*.html?raw" {
  const value: string;
  export default value;
}

declare global {
  interface Window {
    AUTO_CAT_API?: string;
    LoRAForgeCanvas?: {
      centerNode: (id: string) => void;
      fit: () => void;
      getPipelineOptions: () => Record<string, boolean>;
    };
    LoRAForgeI18n?: {
      language: string;
      translate: (value: string) => string;
    };
  }
}
