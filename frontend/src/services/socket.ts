import { io, Socket } from "socket.io-client";

class WebSocketService {
  private socket: Socket | null = null;

  connect(sessionId: string): void {
    if (this.socket) return;

    this.socket = io("http://localhost:8000", { query: { sessionId } });

    this.socket.on("connect", () => {
      console.log("WebSocket connected:", this.socket?.id);
    });

    this.socket.on("disconnect", () => {
      console.log("WebSocket disconnected.");
    });
  }

  on(event: string, callback: (data: any) => void): void {
    if (this.socket) {
      this.socket.on(event, callback);
    }
  }

  disconnect(): void {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
  }
}

export const webSocketService = new WebSocketService();