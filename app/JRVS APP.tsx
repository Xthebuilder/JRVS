'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Mic, MicOff, Calendar, Clock, MessageSquare, Sparkles, Plus, X } from 'lucide-react';

// Types
interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: Date;
}

interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  color: string;
}

interface ConnectedCalendar {
  id: string;
  name: string;
  type: 'google' | 'outlook' | 'apple' | 'custom';
  color: string;
  events: CalendarEvent[];
}

// TechBackground Component
const TechBackground = () => {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-slate-950">
      {/* Grid pattern */}
      <div 
        className="absolute inset-0 opacity-30"
        style={{
          backgroundImage: `
            linear-gradient(rgba(100, 116, 139, 0.5) 1px, transparent 1px),
            linear-gradient(90deg, rgba(100, 116, 139, 0.5) 1px, transparent 1px)
          `,
          backgroundSize: '50px 50px'
        }}
      />
      
      {/* Central orb */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
        <div className="relative w-64 h-64">
          {/* Outer ring */}
          <div 
            className="absolute inset-0 rounded-full border-2 border-cyan-500/30"
            style={{
              animation: 'spin 20s linear infinite'
            }}
          >
            <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-3 bg-cyan-500 rounded-full shadow-[0_0_20px_rgba(6,182,212,0.8)]" />
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-3 h-3 bg-teal-500 rounded-full shadow-[0_0_20px_rgba(20,184,166,0.8)]" />
          </div>
          
          {/* Middle ring */}
          <div 
            className="absolute inset-4 rounded-full border-2 border-teal-500/30"
            style={{
              animation: 'spin 15s linear infinite reverse'
            }}
          >
            <div className="absolute top-1/2 left-0 -translate-x-1/2 -translate-y-1/2 w-2 h-2 bg-teal-400 rounded-full shadow-[0_0_15px_rgba(45,212,191,0.8)]" />
            <div className="absolute top-1/2 right-0 translate-x-1/2 -translate-y-1/2 w-2 h-2 bg-cyan-500 rounded-full shadow-[0_0_15px_rgba(6,182,212,0.8)]" />
          </div>
          
          {/* Inner core */}
          <div className="absolute inset-8 rounded-full bg-gradient-to-br from-cyan-500/20 to-teal-500/20 backdrop-blur-sm shadow-[0_0_60px_rgba(6,182,212,0.4)]">
            <div 
              className="absolute inset-2 rounded-full bg-gradient-to-br from-cyan-500/40 to-teal-500/40"
              style={{
                animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite'
              }}
            />
          </div>
        </div>
      </div>
      
      {/* Tech elements */}
      <div 
        className="absolute top-20 left-20 w-32 h-32 border border-cyan-500/20 rotate-45"
        style={{
          animation: 'spin 30s linear infinite'
        }}
      />
      <div 
        className="absolute bottom-32 right-32 w-24 h-24 border border-teal-500/20"
        style={{
          animation: 'spin 25s linear infinite reverse'
        }}
      />
      
      {/* Circuit lines */}
      <svg className="absolute inset-0 w-full h-full opacity-20" xmlns="http://www.w3.org/2000/svg">
        <line x1="0" y1="50%" x2="30%" y2="50%" stroke="rgb(6, 182, 212)" strokeWidth="2" />
        <line x1="70%" y1="50%" x2="100%" y2="50%" stroke="rgb(6, 182, 212)" strokeWidth="2" />
        <line x1="50%" y1="0" x2="50%" y2="30%" stroke="rgb(20, 184, 166)" strokeWidth="2" />
        <line x1="50%" y1="70%" x2="50%" y2="100%" stroke="rgb(20, 184, 166)" strokeWidth="2" />
      </svg>
    </div>
  );
};

const AISchedulingPlatform = () => {
  // State Management
    const [isRecording, setIsRecording] = useState(false);
    const [userInput, setUserInput] = useState('');
    const [messages, setMessages] = useState<Message[]>([
      {
        id: '1',
        sender: 'assistant',
        text: "Hi! I'm your AI scheduling assistant. Connect your calendars on the right, and I'll help you find the perfect meeting times. What would you like to schedule?",
        timestamp: new Date()
      }
    ]);
    const [calendars, setCalendars] = useState<ConnectedCalendar[]>([]);
    const [showAddCalendar, setShowAddCalendar] = useState(false);
    const [selectedView, setSelectedView] = useState<'week' | 'day'>('week');
    const messagesEndRef = useRef<HTMLDivElement>(null);
  
    // Calendar providers
    const calendarProviders = [
      { type: 'google' as const, name: 'Google Calendar', color: 'bg-blue-500' },
      { type: 'outlook' as const, name: 'Outlook Calendar', color: 'bg-cyan-500' },
      { type: 'apple' as const, name: 'Apple Calendar', color: 'bg-gray-500' },
      { type: 'custom' as const, name: 'Custom Calendar', color: 'bg-purple-500' }
    ];
};

export default AISchedulingPlatform;