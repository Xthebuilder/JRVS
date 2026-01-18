'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Calendar, Clock, MessageSquare, Sparkles, Plus, X } from 'lucide-react';
import { jarvisAPI } from '@/lib/jarvis-api';
import WeekCalendar from './components/WeekCalendar';

// Types
interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: Date;
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
  const [userInput, setUserInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      sender: 'assistant',
      text: "Hi! I'm Jarvis, your AI assistant. I can help you with scheduling, answer questions, manage your calendar, and more. How can I help you today?",
      timestamp: new Date()
    }
  ]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Ref to trigger calendar refresh
  const [calendarRefreshTrigger, setCalendarRefreshTrigger] = useState(0);

  // Handle Send Message
  const handleSendMessage = async () => {
    if (!userInput.trim()) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: userInput,
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMsg]);
    const currentInput = userInput;
    setUserInput('');

    try {
      // Call real Jarvis API
      const response = await jarvisAPI.chat(currentInput);

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: response.response,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, assistantMsg]);

      // Refresh calendar in case event was created
      setCalendarRefreshTrigger(prev => prev + 1);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: 'Sorry, I encountered an error connecting to the Jarvis API. Please make sure the API server is running on http://localhost:8000',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMsg]);
    }
  };

  // Handle Enter key
  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };


  return (
    <>
      <TechBackground />
      <div className="min-h-screen text-white">
        {/* Header */}
        <header className="border-b border-slate-700/50 bg-slate-900/50 backdrop-blur-xl">
          <div className="max-w-[1800px] mx-auto px-6 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gradient-to-br from-sky-500 to-blue-500 rounded-xl flex items-center justify-center">
                  <Sparkles className="w-6 h-6" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold bg-gradient-to-r from-sky-400 to-blue-400 bg-clip-text text-transparent">
                    JRVS
                  </h1>
                  <p className="text-xs text-slate-400">AI Schedule Interface</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <Calendar className="w-4 h-4" />
                  <span>Calendar Sync Active</span>
                </div>
              </div>
            </div>
          </div>
        </header>

        <div className="max-w-[1800px] mx-auto px-6 py-6">
          <div className="flex gap-6 h-[calc(100vh-140px)]">
            {/* Left Side - Chat Interface */}
            <div className="w-1/2 flex flex-col bg-slate-900/50 backdrop-blur-xl border border-slate-700/50 rounded-2xl overflow-hidden">
              {/* Chat Header */}
              <div className="p-4 border-b border-slate-700/50">
                <div className="flex items-center gap-3">
                  <MessageSquare className="w-5 h-5 text-sky-400" />
                  <div>
                    <h2 className="text-lg font-semibold">JRVS AI</h2>
                    <p className="text-xs text-slate-400">Powered by Local Ollama Models</p>
                  </div>
                </div>
              </div>

              {/* Messages Area */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.map((msg) => (
                  <div key={msg.id} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[80%] ${msg.sender === 'user' ? 'order-2' : 'order-1'}`}>
                      {msg.sender === 'assistant' && (
                        <div className="flex items-center gap-2 mb-1">
                          <div className="w-6 h-6 bg-gradient-to-br from-sky-500 to-blue-500 rounded-full flex items-center justify-center text-xs">
                            🤖
                          </div>
                          <span className="text-xs text-slate-400">AI Assistant</span>
                        </div>
                      )}
                      <div className={`rounded-2xl px-4 py-3 ${
                        msg.sender === 'user'
                          ? 'bg-gradient-to-r from-sky-500 to-blue-500'
                          : 'bg-slate-800 border border-slate-700'
                      }`}>
                        <p className="text-sm leading-relaxed whitespace-pre-line">{msg.text}</p>
                      </div>
                      <div className={`text-xs text-slate-500 mt-1 ${msg.sender === 'user' ? 'text-right' : ''}`}>
                        {msg.timestamp.toLocaleTimeString()}
                      </div>
                    </div>
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>

              {/* Input Area */}
              <div className="p-4 border-t border-slate-700/50">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={userInput}
                    onChange={(e) => setUserInput(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Type your message..."
                    className="flex-1 bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent"
                  />
                  <button
                    onClick={handleSendMessage}
                    disabled={!userInput.trim()}
                    className="px-6 py-3 bg-gradient-to-r from-sky-500 to-blue-500 hover:from-sky-600 hover:to-blue-600 disabled:from-slate-700 disabled:to-slate-700 disabled:cursor-not-allowed rounded-xl font-semibold transition-all shrink-0"
                  >
                    Send
                  </button>
                </div>
              </div>
            </div>

            {/* Right Side - Calendar Management */}
            <div className="w-1/2 flex flex-col bg-slate-900/50 backdrop-blur-xl border border-slate-700/50 rounded-2xl overflow-hidden">
              <WeekCalendar key={calendarRefreshTrigger} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AISchedulingPlatform;
