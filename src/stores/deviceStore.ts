import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Device } from '../lib/types'

interface DeviceState {
  devices: Device[]
  selectedDevice: Device | null
  setDevices: (devices: Device[]) => void
  updateDevice: (id: string, updates: Partial<Device>) => void
  addDevice: (device: Device) => void
  removeDevice: (id: string) => void
  selectDevice: (device: Device | null) => void
}

export const useDeviceStore = create<DeviceState>()(
  persist(
    (set) => ({
      devices: [],
      selectedDevice: null,
      setDevices: (devices) => set({ devices }),
      updateDevice: (id, updates) =>
        set((state) => ({
          devices: state.devices.map((d) =>
            d.id === id ? { ...d, ...updates } : d
          ),
        })),
      addDevice: (device) =>
        set((state) => ({
          devices: [...state.devices.filter((d) => d.id !== device.id), device],
        })),
      removeDevice: (id) =>
        set((state) => ({
          devices: state.devices.filter((d) => d.id !== id),
          selectedDevice: state.selectedDevice?.id === id ? null : state.selectedDevice,
        })),
      selectDevice: (device) => set({ selectedDevice: device }),
    }),
    {
      name: 'syncflow-devices',
      partialize: (state) => ({
        devices: state.devices.filter((d) => d.manual),
        selectedDevice: null,
      }),
    }
  )
)
