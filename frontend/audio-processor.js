/**
 * audio-processor.js — AudioWorklet processor for Seenic
 *
 * Pre-allocated Float32Array ring buffer (4 seconds at 48 kHz mono).
 * Write head advances as chunks arrive from the WebSocket.
 * Read head advances at the audio clock rate (128 samples per process() call).
 * No dynamic allocations in the hot path → no GC micro-stutters.
 *
 * NOTE: AudioWorklet modules must be served over HTTPS or localhost.
 * Use ngrok when testing on a physical phone.
 */

const BUFFER_SAMPLES = 48_000 * 4; // 4 s ring buffer

class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Separate ring buffers for left and right channels
    this._left  = new Float32Array(BUFFER_SAMPLES);
    this._right = new Float32Array(BUFFER_SAMPLES);
    this._write = 0;
    this._read  = 0;

    this.port.onmessage = ({ data }) => {
      // data is a Float32Array of interleaved stereo samples [L, R, L, R, ...]
      const frames = data.length / 2;
      for (let i = 0; i < frames; i++) {
        const idx = (this._write + i) % BUFFER_SAMPLES;
        this._left[idx]  = data[i * 2];
        this._right[idx] = data[i * 2 + 1];
      }
      this._write = (this._write + frames) % BUFFER_SAMPLES;
    };
  }

  process(_inputs, outputs) {
    const outL = outputs[0][0];
    const outR = outputs[0][1];

    for (let i = 0; i < outL.length; i++) {
      if (this._read !== this._write) {
        outL[i] = this._left[this._read];
        outR[i] = this._right[this._read];
        this._read = (this._read + 1) % BUFFER_SAMPLES;
      } else {
        // Buffer underrun — output silence
        outL[i] = 0;
        outR[i] = 0;
      }
    }

    return true; // keep processor alive
  }
}

registerProcessor('seenic-audio', AudioProcessor);
