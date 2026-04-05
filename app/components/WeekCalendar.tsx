'use client';

import { useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight, Calendar as CalendarIcon, Clock, X, Check } from 'lucide-react';
import { jarvisAPI, CalendarEvent } from '@/lib/jarvis-api';

export default function WeekCalendar() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [currentWeekStart, setCurrentWeekStart] = useState<Date>(getWeekStart(new Date()));
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [loading, setLoading] = useState(false);

  // Load events when week changes
  useEffect(() => {
    loadEvents();
    const interval = setInterval(loadEvents, 5000); // Refresh every 5 seconds
    return () => clearInterval(interval);
  }, [currentWeekStart]);

  const loadEvents = async () => {
    try {
      const allEvents = await jarvisAPI.getUpcomingEvents(30); // Get 30 days
      setEvents(allEvents);
    } catch (error) {
      console.error('Failed to load events:', error);
    }
  };

  // Helper: Get start of week (Monday)
  function getWeekStart(date: Date): Date {
    const d = new Date(date);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1); // Adjust to Monday
    return new Date(d.setDate(diff));
  }

  // Navigation
  const goToPreviousWeek = () => {
    const newWeek = new Date(currentWeekStart);
    newWeek.setDate(newWeek.getDate() - 7);
    setCurrentWeekStart(newWeek);
  };

  const goToNextWeek = () => {
    const newWeek = new Date(currentWeekStart);
    newWeek.setDate(newWeek.getDate() + 7);
    setCurrentWeekStart(newWeek);
  };

  const goToToday = () => {
    setCurrentWeekStart(getWeekStart(new Date()));
  };

  // Generate week days
  const weekDays = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(currentWeekStart);
    date.setDate(date.getDate() + i);
    return date;
  });

  // Hours to display (6 AM - 10 PM)
  const hours = Array.from({ length: 17 }, (_, i) => i + 6);

  // Get events for a specific day and hour
  const getEventsForSlot = (date: Date, hour: number): CalendarEvent[] => {
    return events.filter(event => {
      const eventDate = new Date(event.event_date);
      return (
        eventDate.toDateString() === date.toDateString() &&
        eventDate.getHours() === hour
      );
    });
  };

  // Format time
  const formatHour = (hour: number): string => {
    if (hour === 0) return '12 AM';
    if (hour === 12) return '12 PM';
    if (hour > 12) return `${hour - 12} PM`;
    return `${hour} AM`;
  };

  // Handle event actions
  const handleCompleteEvent = async (eventId: number) => {
    try {
      await jarvisAPI.completeEvent(eventId);
      await loadEvents();
      setSelectedEvent(null);
    } catch (error) {
      console.error('Failed to complete event:', error);
    }
  };

  const handleDeleteEvent = async (eventId: number) => {
    try {
      await jarvisAPI.deleteEvent(eventId);
      await loadEvents();
      setSelectedEvent(null);
    } catch (error) {
      console.error('Failed to delete event:', error);
    }
  };

  const isToday = (date: Date): boolean => {
    const today = new Date();
    return date.toDateString() === today.toDateString();
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <CalendarIcon className="w-5 h-5 text-sky-400" />
            <h2 className="text-lg font-semibold">Week View</h2>
          </div>
          <button
            onClick={goToToday}
            className="px-3 py-1.5 bg-sky-500/20 hover:bg-sky-500/30 border border-sky-500/50 rounded-lg text-xs font-medium transition-all"
          >
            Today
          </button>
        </div>

        {/* Week Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={goToPreviousWeek}
            className="p-2 hover:bg-slate-700 rounded-lg transition-all"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>

          <div className="text-center">
            <div className="text-sm font-semibold">
              {currentWeekStart.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
            </div>
            <div className="text-xs text-slate-400">
              Week of {currentWeekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </div>
          </div>

          <button
            onClick={goToNextWeek}
            className="p-2 hover:bg-slate-700 rounded-lg transition-all"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Calendar Grid */}
      <div className="flex-1 overflow-auto">
        <div className="min-w-[800px]">
          {/* Day Headers */}
          <div className="grid grid-cols-8 border-b border-slate-700/50 bg-slate-900/50 sticky top-0 z-10">
            <div className="p-2 text-xs font-medium text-slate-500">Time</div>
            {weekDays.map((day, idx) => (
              <div
                key={idx}
                className={`p-2 text-center border-l border-slate-700/50 ${
                  isToday(day) ? 'bg-sky-500/10' : ''
                }`}
              >
                <div className="text-xs font-medium text-slate-400">
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </div>
                <div
                  className={`text-lg font-semibold ${
                    isToday(day) ? 'text-sky-400' : ''
                  }`}
                >
                  {day.getDate()}
                </div>
              </div>
            ))}
          </div>

          {/* Time Slots */}
          <div className="relative">
            {hours.map((hour) => (
              <div key={hour} className="grid grid-cols-8 border-b border-slate-700/30">
                {/* Hour Label */}
                <div className="p-2 text-xs text-slate-500 font-medium border-r border-slate-700/30">
                  {formatHour(hour)}
                </div>

                {/* Day Columns */}
                {weekDays.map((day, dayIdx) => {
                  const slotEvents = getEventsForSlot(day, hour);
                  const isCurrentHour = isToday(day) && new Date().getHours() === hour;

                  return (
                    <div
                      key={dayIdx}
                      className={`min-h-[60px] p-1 border-l border-slate-700/30 relative ${
                        isCurrentHour ? 'bg-sky-500/5' : ''
                      } ${isToday(day) ? 'bg-slate-800/30' : ''}`}
                    >
                      {slotEvents.map((event) => (
                        <button
                          key={event.id}
                          onClick={() => setSelectedEvent(event)}
                          className="w-full mb-1 p-2 bg-sky-500/20 hover:bg-sky-500/30 border border-sky-500/50 rounded text-left transition-all"
                        >
                          <div className="text-xs font-medium text-sky-300 truncate">
                            {event.title}
                          </div>
                          <div className="text-[10px] text-slate-400 flex items-center gap-1">
                            <Clock className="w-2.5 h-2.5" />
                            {new Date(event.event_date).toLocaleTimeString('en-US', {
                              hour: 'numeric',
                              minute: '2-digit'
                            })}
                          </div>
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Event Details Modal */}
      {selectedEvent && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50"
          onClick={() => setSelectedEvent(null)}
        >
          <div
            className="bg-slate-800 border border-slate-700 rounded-2xl p-6 max-w-md w-full m-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-xl font-semibold mb-1">{selectedEvent.title}</h3>
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <Clock className="w-4 h-4" />
                  {new Date(selectedEvent.event_date).toLocaleString('en-US', {
                    weekday: 'long',
                    month: 'long',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit'
                  })}
                </div>
              </div>
              <button
                onClick={() => setSelectedEvent(null)}
                className="p-2 hover:bg-slate-700 rounded-lg transition-all"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {selectedEvent.description && (
              <div className="mb-4">
                <div className="text-xs text-slate-400 mb-1">Description</div>
                <p className="text-sm text-slate-300">{selectedEvent.description}</p>
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => handleCompleteEvent(selectedEvent.id!)}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-500/20 hover:bg-green-500/30 border border-green-500/50 rounded-lg text-green-400 text-sm font-medium transition-all"
              >
                <Check className="w-4 h-4" />
                Complete
              </button>
              <button
                onClick={() => handleDeleteEvent(selectedEvent.id!)}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/50 rounded-lg text-red-400 text-sm font-medium transition-all"
              >
                <X className="w-4 h-4" />
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stats Footer */}
      <div className="p-3 border-t border-slate-700/50 bg-slate-900/50">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>{events.length} total events</span>
          <button
            onClick={loadEvents}
            className="hover:text-sky-400 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
