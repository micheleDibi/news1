declare module '@splidejs/splide' {
  export default class Splide {
    constructor(target: string | Element, options?: any);
    mount(): void;
    destroy(): void;
  }
}

declare module '@splidejs/splide/dist/css/splide.min.css' {
  const content: any;
  export default content;
} 