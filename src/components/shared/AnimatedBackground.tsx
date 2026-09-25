import { useEffect, useRef } from 'react'

export function AnimatedBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let particles: Particle[] = []
    let w = canvas.width
    let h = canvas.height

    const resize = () => {
      w = window.innerWidth
      h = window.innerHeight
      canvas.width = w
      canvas.height = h
    }

    class Particle {
      x: number
      y: number
      vx: number
      vy: number
      radius: number
      opacity: number
      color: string

      constructor() {
        this.x = Math.random() * w
        this.y = Math.random() * h
        this.vx = (Math.random() - 0.5) * 0.3
        this.vy = (Math.random() - 0.5) * 0.3
        this.radius = Math.random() * 1.5 + 0.5
        this.opacity = Math.random() * 0.3 + 0.05
        this.color = Math.random() > 0.5 ? '0, 212, 170' : '59, 130, 246'
      }

      update() {
        this.x += this.vx
        this.y += this.vy

        if (this.x < 0 || this.x > w) this.vx *= -1
        if (this.y < 0 || this.y > h) this.vy *= -1
      }

      draw() {
        ctx!.beginPath()
        ctx!.arc(this.x, this.y, this.radius, 0, Math.PI * 2)
        ctx!.fillStyle = `rgba(${this.color}, ${this.opacity})`
        ctx!.fill()
      }
    }

    const initParticles = () => {
      const count = Math.min(50, Math.floor((w * h) / 20000))
      particles = Array.from({ length: count }, () => new Particle())
    }

    const drawConnections = () => {
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < 150) {
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.strokeStyle = `rgba(0, 212, 170, ${0.03 * (1 - dist / 150)})`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
      }
    }

    const animate = () => {
      if (!document.hidden) {
        ctx.clearRect(0, 0, w, h)

        particles.forEach((p) => {
          p.update()
          p.draw()
        })

        drawConnections()
      }
      animationId = requestAnimationFrame(animate)
    }

    const onResize = () => {
      resize()
      initParticles()
    }

    resize()
    initParticles()
    animate()

    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(animationId)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 0 }}
    />
  )
}
