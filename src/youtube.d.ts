interface YT {
  Player: {
    new (elementId: string, config: any): YT.Player;
  };
}

interface Window {
  YT: YT;
  onYouTubeIframeAPIReady: () => void;
} 