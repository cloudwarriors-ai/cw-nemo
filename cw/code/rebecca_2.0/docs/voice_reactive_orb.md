Voice assistants are evolving beyond simple text or speech responses. Modern designs often use flowing, organic animations that react to sound to make conversations feel more alive. In this tutorial, we’ll build an iridescent orb that visually responds to your voice input using React, the Web Audio API, OGL (a lightweight WebGL engine) and components from React Bits.

https://www.reactbits.dev/backgrounds/iridescence

Get Dan Jackson’s stories in your inbox
Join Medium for free to get updates from this writer.

Enter your email
Subscribe
The visual effect combines a glowing sphere rendered in a fragment shader with a real-time audio analyzer that influences its movement and brightness.


Step 1. Capturing and Normalizing Audio Input
The useAudioLevel hook connects to the microphone and measures average amplitude in real time. It exposes a smoothed volume level that the visual layer can react to.

function useAudioLevel() {
  const levelRef = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number>(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    ctxRef.current?.close();
    streamRef.current?.getTracks().forEach(t => t.stop());
  }, []);

  const start = useCallback(async () => {
    stop();
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      ctxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const source = ctx.createMediaStreamSource(stream);
      source.connect(analyser);
      analyserRef.current = analyser;

      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b) / data.length;
        const norm = Math.min(1, Math.max(0, (avg - 16) / 90));
        levelRef.current += (norm - levelRef.current) * 0.15;
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
      setReady(true);
    } catch (err: any) {
      setError(err.message);
    }
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { levelRef, ready, error, start };
}
Step 2. Creating the Orb Component
The main React component renders the orb and applies transformations driven by the live audio level.

export default function VoiceOrbIridescencePage() {
  const { levelRef, ready, error, start } = useAudioLevel();
  const [level, setLevel] = useState(0);
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    let raf = 0;
    const update = () => {
      setLevel(prev => prev + (levelRef.current - prev) * 0.25);
      raf = requestAnimationFrame(update);
    };
    update();
    return () => cancelAnimationFrame(raf);
  }, [levelRef]);

  const amplitude = 0.18 + level * 1.7;
  const speed = 0.75 + level * 0.5;
  const scale = 1 + level * 0.35;
  const glowOpacity = 0.25 + level * 2.45;

  return (
    <div className={`relative flex min-h-screen items-center justify-center ${isDark ? "bg-black text-white" : "bg-white text-black"}`}>
      <div className="relative w-[200px] aspect-square">
        <div className="absolute inset-0 rounded-full bg-blue-500 blur-[130px]" style={{ opacity: glowOpacity }} />
        <div className="relative h-full w-full rounded-full overflow-hidden shadow-[0_0_90px_rgba(58,108,255,0.45)]" style={{ transform: `scale(${scale})`, transition: "transform 0.12s ease-out" }}>
          <Iridescence amplitude={amplitude} speed={speed} color={[0.3, 0.6, 1]} />
        </div>
      </div>

      <div className="absolute bottom-10 flex flex-col items-center gap-3 text-sm">
        {!ready && <button onClick={start} className="border px-4 py-2 rounded">Enable Microphone</button>}
        {error && <div>Audio error: {error}</div>}
        <button onClick={() => setIsDark(prev => !prev)} className="text-xs underline">Toggle Theme</button>
      </div>
    </div>
  );
}
The amplitude, speed, and scale values are dynamic, giving the orb a breathing, audio-reactive presence.

Step 3. Rendering the Iridescent Shader
We use OGL to create a full-screen triangle and a fragment shader that generates the iridescent texture.

import { Color, Mesh, Program, Renderer, Triangle } from "ogl";

const vertexShader = `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0, 1);
}
`;

const fragmentShader = `
precision highp float;
uniform float uTime;
uniform vec3 uColor;
uniform vec3 uResolution;
uniform vec2 uMouse;
uniform float uAmplitude;
uniform float uSpeed;
varying vec2 vUv;
void main() {
  float mr = min(uResolution.x, uResolution.y);
  vec2 uv = (vUv * 2.0 - 1.0) * uResolution.xy / mr;
  float d = -uTime * 0.5 * uSpeed;
  float a = 0.0;
  for (float i = 0.0; i < 8.0; ++i) {
    a += cos(i - d - a * uv.x);
    d += sin(uv.y * i + a);
  }
  vec3 col = vec3(cos(uv * vec2(d, a)) * 0.6 + 0.4, cos(a + d) * 0.5 + 0.5);
  col = cos(col * cos(vec3(d, a, 2.5)) * 0.5 + 0.5) * uColor;
  gl_FragColor = vec4(col, 1.0);
}
`;

export default function Iridescence({ color = [0.3, 0.6, 1], speed = 0.1, amplitude = 0.1 }) {
  const container = useRef<HTMLDivElement | null>(null);
  const programRef = useRef<Program | null>(null);

  useEffect(() => {
    const renderer = new Renderer();
    const { gl } = renderer;
    const geometry = new Triangle(gl);
    const program = new Program(gl, {
      vertex: vertexShader,
      fragment: fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: new Color(...color) },
        uResolution: { value: new Color(gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height) },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uAmplitude: { value: amplitude },
        uSpeed: { value: speed },
      },
    });
    const mesh = new Mesh(gl, { geometry, program });
    renderer.setSize(400, 400);
    const animate = (t: number) => {
      program.uniforms.uTime.value = t * 0.001;
      renderer.render({ scene: mesh });
      requestAnimationFrame(animate);
    };
    animate(0);
    container.current?.appendChild(gl.canvas);
    programRef.current = program;
    return () => gl.getExtension("WEBGL_lose_context")?.loseContext();
  }, []);

  return <div ref={container} className="w-full h-full" />;
}
The fragment shader uses layered cosine patterns to create subtle, refracting color flows, giving the orb a smooth iridescent look.

Step 4. Combining Everything
When you put it all together, you get a fluid, microphone-driven orb that glows and ripples in sync with your voice.

Speak louder and the orb pulses faster.
Speak softly and it gently breathes.
Switch between light and dark themes for contrast.
This component can be easily embedded into any voice assistant UI or creative audio project.

This project demonstrates how React can integrate with Web Audio and WebGL to produce expressive, real-time visuals. By combining a simple audio analysis algorithm with GLSL shaders, you can create engaging, voice-reactive interfaces that feel alive.

The techniques here can be extended for waveforms, spectral rings, or particle systems — all driven by sound energy.

Experiment with different shader color models, easing curves, and geometric distortions to give your assistant its own personality.