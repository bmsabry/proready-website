import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Calendar, Clock, Users, BookOpen, Search, Filter, ArrowRight } from 'lucide-react';

const courses = [
  {
    id: 1,
    title: "Advanced Combustion Fundamentals",
    category: "Thermal Fluids",
    duration: "3 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Core combustion theory with practical applications for modern energy systems.",
    nextDate: "By request"
  },
  {
    id: 2,
    title: "Gas Turbine Combustion",
    category: "Thermal Fluids",
    duration: "3 Days",
    level: "Advanced",
    attendees: "15 Max",
    description: "Stability, emissions, and performance considerations for gas turbine combustors.",
    nextDate: "By request"
  },
  {
    id: 3,
    title: "Fundamentals of Turbomachinery",
    category: "Thermal Fluids",
    duration: "2 Days",
    level: "Foundational",
    attendees: "25 Max",
    description: "Fundamental principles of compressors, turbines, and overall cycle performance.",
    nextDate: "By request"
  },
  {
    id: 4,
    title: "Data Visualization & Advanced Analytics",
    category: "AI & Data",
    duration: "2 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Turn complex data into clear, decision-ready engineering insights.",
    nextDate: "By request"
  },
  {
    id: 5,
    title: "Applied Machine Learning & AI for Engineers",
    category: "AI & Data",
    duration: "4 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Practical ML workflows tailored to engineering datasets and constraints.",
    nextDate: "By request"
  },
  {
    id: 6,
    title: "CFD Best Practices & Simulation",
    category: "Thermal Fluids",
    duration: "2 Days",
    level: "Intermediate",
    attendees: "15 Max",
    description: "Mesh generation, turbulence modeling, and solver strategy for robust CFD.",
    nextDate: "By request"
  },
  {
    id: 7,
    title: "Custom Corporate Training Programs",
    category: "Thermal Fluids",
    duration: "Custom",
    level: "All Levels",
    attendees: "Team-based",
    description: "Tailored programs aligned to your systems, data, and business goals.",
    nextDate: "Schedule with us"
  }
];

const Training = () => {
  const [filter, setFilter] = useState('All');
  const categories = ['All', 'Thermal Fluids', 'AI & Data'];

  const filteredCourses = filter === 'All' 
    ? courses 
    : courses.filter(c => c.category === filter);

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-16">
          <div className="max-w-2xl">
            <h1 className="text-4xl md:text-5xl font-bold mb-6">Training & <span className="text-gradient">Workshops</span></h1>
            <p className="text-slate-400 text-lg">
              Upskill your engineering team with our specialized technical courses. 
              We offer both scheduled public workshops and custom corporate training.
            </p>
          </div>
          
          <div className="flex items-center gap-4 bg-slate-900 p-1 rounded-xl border border-slate-800">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setFilter(cat)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  filter === cat 
                    ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-900/20' 
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {filteredCourses.map((course, i) => (
            <motion.div
              key={course.id}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.1 }}
              className="group bg-slate-900/50 border border-slate-800 rounded-3xl p-8 hover:border-cyan-500/50 transition-all flex flex-col"
            >
              <div className="flex justify-between items-start mb-6">
                <span className="px-3 py-1 rounded-full bg-slate-800 text-cyan-400 text-xs font-mono uppercase tracking-wider border border-slate-700">
                  {course.category}
                </span>
              </div>
              
              <h3 className="text-2xl font-bold mb-4 group-hover:text-cyan-400 transition-colors">{course.title}</h3>
              <p className="text-slate-400 text-sm mb-8 flex-grow leading-relaxed">
                {course.description}
              </p>

              <div className="grid grid-cols-2 gap-4 mb-8">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Clock className="w-4 h-4 text-slate-600" />
                  <span>{course.duration}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <BookOpen className="w-4 h-4 text-slate-600" />
                  <span>{course.level}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Users className="w-4 h-4 text-slate-600" />
                  <span>{course.attendees}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Calendar className="w-4 h-4 text-slate-600" />
                  <span>Next: {course.nextDate}</span>
                </div>
              </div>

              <button className="w-full py-3 rounded-xl bg-slate-800 hover:bg-cyan-600 text-white font-semibold transition-all flex items-center justify-center gap-2 group/btn">
                View Course Details <ArrowRight className="w-4 h-4 group-hover/btn:translate-x-1 transition-transform" />
              </button>
            </motion.div>
          ))}
        </div>

        {/* Custom Training CTA */}
        <div className="mt-20 p-12 rounded-[3rem] bg-gradient-to-r from-cyan-900/20 to-blue-900/20 border border-cyan-500/20 text-center">
          <h2 className="text-3xl font-bold mb-4">Need a Custom Workshop?</h2>
          <p className="text-slate-400 max-w-2xl mx-auto mb-8">
            We can tailor any of our courses to your specific industry challenges and data sets. 
            Available for on-site or remote delivery.
          </p>
          <button className="btn-primary">Request Custom Training</button>
        </div>
      </div>
    </div>
  );
};

export default Training;