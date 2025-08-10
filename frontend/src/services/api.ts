import axios from "axios";

const API_BASE_URL = "http://localhost:8000";

export const uploadAudio = async (file: File): Promise<any> => {
  const formData = new FormData();
  formData.append("file", file);

  const response = await axios.post(`${API_BASE_URL}/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  return response.data;
};

export const startTranscription = async (audioFilename: string, sessionId: string): Promise<any> => {
  const response = await axios.post(`${API_BASE_URL}/transcribe`, {
    audio_filename: audioFilename,
  }, {
    headers: { "X-Session-ID": sessionId },
  });

  return response.data;
};