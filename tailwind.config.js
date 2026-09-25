/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        navy: {
          900: '#0A1628',
          800: '#0D1F35',
          700: '#132D45',
          600: '#1A3A5C',
        },
        aqua: {
          900: '#0D2B3E',
          800: '#123A52',
          700: '#1A4D6B',
          600: '#1E6080',
        },
        cyber: {
          teal: '#00D4AA',
          blue: '#3B82F6',
          glow: 'rgba(0, 212, 170, 0.2)',
        },
        frost: {
          100: '#E2E8F0',
          200: '#CBD5E1',
          300: '#94A3B8',
          400: '#64748B',
        },
      },
      boxShadow: {
        'glow': '0 0 20px rgba(0, 212, 170, 0.15)',
        'glow-lg': '0 0 40px rgba(0, 212, 170, 0.2)',
        'glow-blue': '0 0 20px rgba(59, 130, 246, 0.15)',
        'glass': '0 8px 32px rgba(0, 0, 0, 0.3)',
      },
      backdropBlur: {
        'glass': '16px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'float': 'float 6s ease-in-out infinite',
        'wave': 'wave 2s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(0, 212, 170, 0.1)' },
          '100%': { boxShadow: '0 0 25px rgba(0, 212, 170, 0.3)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        wave: {
          '0%': { transform: 'scaleX(0)' },
          '50%': { transform: 'scaleX(1)' },
          '100%': { transform: 'scaleX(0)' },
        },
      },
    },
  },
  plugins: [],
}
