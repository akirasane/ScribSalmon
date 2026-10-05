// Adapted from React Bits (reactbits.dev) - Aurora (WebGL via ogl)
import { useEffect, useRef } from 'react'
import { Renderer, Program, Mesh, Color, Triangle } from 'ogl'

const VERT = `#version 300 es
in vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`

const FRAG = `#version 300 es
precision highp float;
uniform float uTime;
uniform float uAmplitude;
uniform vec3 uColorStops[3];
uniform vec2 uResolution;
uniform float uBlend;
out vec4 fragColor;

vec3 permute(vec3 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  vec3 rampColor = uv.x < 0.5 ? mix(uColorStops[0], uColorStops[1], uv.x * 2.0)
                              : mix(uColorStops[1], uColorStops[2], (uv.x - 0.5) * 2.0);
  float height = snoise(vec2(uv.x * 2.0 + uTime * 0.1, uTime * 0.25)) * 0.5 * uAmplitude;
  height = exp(height);
  height = (uv.y * 2.0 - height + 0.2);
  float intensity = 0.6 * height;
  float auroraAlpha = smoothstep(0.20 - uBlend * 0.5, 0.20 + uBlend * 0.5, intensity);
  fragColor = vec4(intensity * rampColor * auroraAlpha, auroraAlpha);
}
`

interface Props {
  colorStops?: string[]
  amplitude?: number
  blend?: number
  speed?: number
}

export default function Aurora({ colorStops = ['#ff8a73', '#ffc65c', '#ff8a73'], amplitude = 1, blend = 0.6, speed = 0.6 }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ctn = ref.current
    if (!ctn) return
    let renderer: Renderer
    try {
      renderer = new Renderer({ alpha: true, premultipliedAlpha: true, antialias: false, dpr: 1 })
    } catch {
      return // no WebGL: skip decoration
    }
    const gl = renderer.gl
    gl.clearColor(0, 0, 0, 0)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    gl.canvas.style.backgroundColor = 'transparent'

    const geometry = new Triangle(gl)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if ((geometry.attributes as any).uv) delete (geometry.attributes as any).uv
    const stops = colorStops.map((h) => {
      const c = new Color(h)
      return [c.r, c.g, c.b]
    })
    const program = new Program(gl, {
      vertex: VERT,
      fragment: FRAG,
      uniforms: {
        uTime: { value: 0 },
        uAmplitude: { value: amplitude },
        uColorStops: { value: stops },
        uResolution: { value: [ctn.offsetWidth, ctn.offsetHeight] },
        uBlend: { value: blend },
      },
    })
    const mesh = new Mesh(gl, { geometry, program })
    ctn.appendChild(gl.canvas)

    const resize = () => {
      renderer.setSize(ctn.offsetWidth, ctn.offsetHeight)
      program.uniforms.uResolution.value = [ctn.offsetWidth, ctn.offsetHeight]
    }
    window.addEventListener('resize', resize)
    resize()

    let raf = 0
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop)
      program.uniforms.uTime.value = t * 0.001 * speed
      renderer.render({ scene: mesh })
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      if (gl.canvas.parentNode === ctn) ctn.removeChild(gl.canvas)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <div ref={ref} className="h-full w-full" />
}
