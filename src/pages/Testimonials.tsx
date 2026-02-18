import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Quote, Star, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

const Testimonials = () => {
  const [activeFeatured, setActiveFeatured] = useState(0);

  // All testimonials from the combined document
  const allTestimonials = [
    {
      name: "Mark Mueller",
      role: "Senior Product Manager - LM2500 Fleet",
      statement: "Relative to completing a commitment, you are the most dedicated and committed person that I know. And, you do it with joy.",
      category: "Dedication"
    },
    {
      name: "Kwanwoo Kim",
      role: "Principal Engineer - Acoustics - Chief Engineering",
      statement: "I believe 'passionate' is the first thing I can think of your great work ethics. You have shown enthusiasm, passion, humility and engaging team members in all team meetings. Also, you voice your opinions/concerns with transparency. You look for continuous improvements, not settling with the status-quo in many of engineering analyses.",
      category: "Passion & Ethics"
    },
    {
      name: "Giridharan Manampathy",
      role: "Sr Engineer - Systems Engineering - GE Vernova",
      statement: "Energetic, enthusiastic, accountable, and can do attitude, are the words I would use to describe you.",
      category: "Attitude"
    },
    {
      name: "Keith McManus",
      role: "Technology Manager - Combustion",
      statement: "A person who puts others first, not themself.",
      category: "Selflessness"
    },
    {
      name: "Ahmed Elkady",
      role: "Sr Engineering Manager - Systems Engineering Management",
      statement: "Dedicated and owns the technical problem until it gets resolved. Bassam is very passionate about what he does, and one of the few I could see can spend hours talking about the work being done, latest developments, and seeking opinion to further improve the status que.",
      category: "Passion & Problem Solving"
    },
    {
      name: "Casey Brooke",
      role: "Staff Engineer - Mechanical Engineering",
      statement: "From my perspective you do a phenomenal job and are great to work with and talk with personally. You seem to be a high performing aero engineer.",
      category: "Performance"
    },
    {
      name: "Daniel Rosato",
      role: "Research Engineer – Combustion Emissions Testing & validation",
      statement: "An unyielding force for engineering excellence and delivery",
      category: "Excellence"
    },
    {
      name: "Mohnish Peswani",
      role: "Lead Engineer – Combustion Aero",
      statement: "Extremely motivated and passionate and a very kind person and wonderful mentor.",
      category: "Mentorship"
    },
    {
      name: "Jeffrey A Ruszczyk",
      role: "Technician - Mechanical",
      statement: "Dedicated, knowledgeable, professional, caring and friendly. You truly are one of the best people I've known in my life. I admire you Bassam and miss my time working with you. You continue to be an asset to this company and humanity.",
      category: "Character"
    },
    {
      name: "Brian Volk",
      role: "Technician - Mechanical",
      statement: "Bassam Abdelnabi……one of the most compassionate, intelligent, dedicated and determined human beings that I know that makes everything and everyone around him better. I am also very fortunate to not only call him my former coworker but my good friend.",
      category: "Character & Impact"
    },
    {
      name: "Tom Dyson",
      role: "Senior Engineer - Component Heat Transfer",
      statement: "You're a creative engineering mind who's not afraid to bend the rules.",
      category: "Creativity"
    },
    {
      name: "Gregory Johnson",
      role: "Sr Engineer - Technology Support Mechanical",
      statement: "You are an incredibly passionate, knowledgeable and dedicated worker that I enjoy working with and making hardware for. I believe your priorities are correct in that you realize everything you do in God's name is a gift to Him so it should be done to the best of your abilities, regardless of what it is.",
      category: "Values & Dedication"
    },
    {
      name: "Krishna Venkatesan",
      role: "Principal Engineer - Combustion",
      statement: "In my interactions with you, I have observed that you were always direct and shared your honest opinion and not what others wanted to hear. I also recollect how you were able to systematically improve the test cell 4 capabilities which can be very challenging considering the funding and schedule impacts.",
      category: "Integrity & Impact"
    },
    {
      name: "Brian Sharpe",
      role: "Miller Energy, General Manager, NY Office",
      statement: "I have always enjoyed working with you and discussing your pressure and flow applications. Whether discussing these on the flow or in person, I always look forward to your calls.",
      category: "Collaboration"
    },
    {
      name: "Amin Monfared",
      role: "Director, Pool Sales & Marketing @ Raypak",
      statement: "I worked closely with Bassam in GE Global Research for a few years. Bassam was super open and transparent from day one and he really cared about sharing his knowledge and experiences with others. He took ownership of his programs and paid attention to details to deliver innovative solutions to complex problems. He respected people around him and didn't change his behavior when interacting with a lab technician or a Vice President. Bassam revolutionized how we performed testing and constantly improved the test hardware, instrumentations, sensor technologies, etc. I can for sure say he is the best engineer I have ever met & worked with.",
      category: "Leadership & Innovation"
    },
    {
      name: "Gulacar Dogan",
      role: "GE Aerospace – Mechanical lead engineer",
      statement: "Working with Bassam is always educational. He is expert in his field and likes to teach to others. He always supported me whenever I have any questions.",
      category: "Teaching"
    },
    {
      name: "Ajoy Patra",
      role: "GE Aerospace – Senior combustion CFD engineer",
      statement: "Bassam is open to team's inputs and always encourage team to deliver on programs to solve the engine issues. He always keep team updated with programs with thoughtful insights. He is always available to support team and respond to queries.",
      category: "Team Leadership"
    },
    {
      name: "JP Sandino",
      role: "GE Aerospace – Senior Field Support Engineer",
      statement: "For the most part you have been at the forefront of the mapping. I have also seen an improvement on your teamwork skills within the organization. Overall, I am impressed with your knowledge of the DLE system and your willingness to share that knowledge.",
      category: "Knowledge Sharing"
    },
    {
      name: "David Schmidt",
      role: "Tektronix flow measurements lead",
      statement: "Working with you has been a pleasure because of your warm, kind personality, your deep wisdom of your craft, and your open-mindedness to collaborate on the task at hand.",
      category: "Collaboration"
    },
    {
      name: "Steven Vise",
      role: "GE Aerospace Chief Engineer",
      statement: "I've always been amazed with your deep analytical skills, especially using 'digital twin' models to help us gain insight into and solve complex problems on our AEO combustion systems. I also appreciate your tremendous passion for finding customer solutions, which has made a real difference as we introduce our LMS-100 product.",
      category: "Technical Excellence"
    },
    {
      name: "Michael Benjamin",
      role: "GE Aerospace Chief Consulting Engineer",
      statement: "You have passion, passion and more passion that we all enjoy, for emissions, digital twins, and customer satisfaction. Thank you for pursuing the LMS-100 product with such commitment and perseverance, and keep enjoying the journey!",
      category: "Passion & Perseverance"
    },
    {
      name: "Fei Han",
      role: "GE Aerospace Senior Principal acoustics engineer",
      statement: "I've never seen a person more passionate than you in terms of championing new technologies, creating impact for customers, and just getting things done!",
      category: "Passion & Results"
    },
    {
      name: "Jeffrey Ruszczyk",
      role: "GE Aerospace Research Tech",
      statement: "It has been incredible to work with you all these years. Your dedication, determination and expertise is truly amazing and inspiring. You have also been a great friend who is caring and compassionate.",
      category: "Dedication & Friendship"
    },
    {
      name: "Janith Samarasinghe",
      role: "GE Aerospace senior acoustics experimentalist",
      statement: "You are one of the most passionate engineers I've seen in the company when it comes to championing new technologies and delivering solutions to the customer, be it at research or at the business.",
      category: "Passion & Innovation"
    },
    {
      name: "Nicholas Magina",
      role: "GE Aerospace senior acoustics engineer",
      statement: "Not only 15 years of service with GE Aerospace, but 15 years of dedication, passion, and leadership. You are a champion of both technology and people, and are a true crown jewel for GE.",
      category: "Dedication & Leadership"
    },
    {
      name: "Christopher Immer",
      role: "Senior Scientist - Embedded Computing",
      statement: "Bassam is an amazing collaborator who has an acute focus on the goals of his program as evidenced by the inclusive, innovative, proactive work habits he uses to achieve impactful outcomes not only for his program needs, but for GE Aerospace as a whole.",
      category: "Collaboration"
    },
    {
      name: "Andrew Hubble",
      role: "Advanced Lead Engineer – Combustion Aero",
      statement: "I know the work you do is top-tier (because everyone says so), but as someone who doesn't regularly work with you, the thing I find most remarkable has been your ability to explain your process and the results in an incredibly clear and organized way.",
      category: "Communication"
    },
    {
      name: "Daniele Sassi",
      role: "Baker Hughes – LNGC Site Lead",
      statement: "I can only reiterate how much I appreciate your work. Your technical skills and professionalism are outstanding, and you have my full respect both as an engineer and as a person.",
      category: "Professional Respect"
    },
    {
      name: "Donadieu, Jorge",
      role: "GE Aerospace Externals Principal Engineer",
      statement: "Your reply to my inquiries have been in an expeditious manner that quite frankly, is more than I would usually expect or have experienced with other module collaborators.",
      category: "Responsiveness"
    },
    {
      name: "Peter Imler",
      role: "Stratasys Direct Manufacturing Project Engineer",
      statement: "Congratulations on 14 years at GE! It's always been a pleasure to work with you on past projects. You've been very fair, respectful, and knowledgeable in working through projects and coming up with solutions when issues arise.",
      category: "Collaboration"
    }
  ];

  // Top 10 featured testimonials from different people
  const featuredTestimonials = [
    {
      name: "Kwanwoo Kim",
      role: "Principal Engineer - Acoustics - Chief Engineering",
      statement: "I believe 'passionate' is the first thing I can think of your great work ethics. You have shown enthusiasm, passion, humility and engaging team members in all team meetings. Also, you voice your opinions/concerns with transparency.",
      highlight: "Passion & Work Ethics"
    },
    {
      name: "Amin Monfared",
      role: "Director, Pool Sales & Marketing @ Raypak",
      statement: "Bassam was super open and transparent from day one. He took ownership of his programs and paid attention to details to deliver innovative solutions. He respected people around him and didn't change his behavior when interacting with a lab technician or a Vice President.",
      highlight: "Leadership & Innovation"
    },
    {
      name: "Krishna Venkatesan",
      role: "Principal Engineer - Combustion",
      statement: "You were always direct and shared your honest opinion and not what others wanted to hear. You were able to systematically improve the test cell 4 capabilities which can be very challenging.",
      highlight: "Integrity & Impact"
    },
    {
      name: "Jeffrey A Ruszczyk",
      role: "Technician - Mechanical",
      statement: "Dedicated, knowledgeable, professional, caring and friendly. You truly are one of the best people I've known in my life. You continue to be an asset to this company and humanity.",
      highlight: "Character & Excellence"
    },
    {
      name: "Nicholas Magina",
      role: "GE Aerospace senior acoustics engineer",
      statement: "Not only 15 years of service with GE Aerospace, but 15 years of dedication, passion, and leadership. You are a champion of both technology and people, and are a true crown jewel for GE.",
      highlight: "Dedication & Leadership"
    },
    {
      name: "Brian Volk",
      role: "Technician - Mechanical",
      statement: "One of the most compassionate, intelligent, dedicated and determined human beings that I know that makes everything and everyone around him better. I am very fortunate to call him my good friend.",
      highlight: "Character & Impact"
    },
    {
      name: "Steven Vise",
      role: "GE Aerospace Chief Engineer",
      statement: "I've always been amazed with your deep analytical skills, especially using 'digital twin' models to help us gain insight into and solve complex problems. Your passion for finding customer solutions has made a real difference.",
      highlight: "Technical Excellence"
    },
    {
      name: "Ajoy Patra",
      role: "GE Aerospace – Senior combustion CFD engineer",
      statement: "Bassam is open to team's inputs and always encourages team to deliver on programs. He is always available to support team and respond to queries. He has profound combustion knowledge and clear thoughts.",
      highlight: "Team Leadership"
    },
    {
      name: "Daniele Sassi",
      role: "Baker Hughes – LNGC Site Lead",
      statement: "Your technical skills and professionalism are outstanding, and you have my full respect both as an engineer and as a person. That's exactly why I continue to rely on your support more and more.",
      highlight: "Professional Excellence"
    },
    {
      name: "Andrew Hubble",
      role: "Advanced Lead Engineer – Combustion Aero",
      statement: "The thing I find most remarkable has been your ability to explain your process and results in an incredibly clear and organized way. When you give a presentation I can actually follow along.",
      highlight: "Communication Skills"
    }
  ];

  // Sentiment analysis data for the chart
  const sentimentData = [
    { name: 'Passion & Enthusiasm', value: 9, color: '#f59e0b' },
    { name: 'Technical Excellence', value: 6, color: '#06b6d4' },
    { name: 'Leadership & Teamwork', value: 7, color: '#8b5cf6' },
    { name: 'Character & Kindness', value: 5, color: '#10b981' },
    { name: 'Innovation & Creativity', value: 4, color: '#f97316' },
  ];

  const nextFeatured = () => {
    setActiveFeatured((prev) => (prev + 1) % featuredTestimonials.length);
  };

  const prevFeatured = () => {
    setActiveFeatured((prev) => (prev - 1 + featuredTestimonials.length) % featuredTestimonials.length);
  };

  return (
    <div className="pt-20 min-h-screen">
      {/* Hero Section */}
      <section className="relative py-16 overflow-hidden">
        <div className="absolute inset-0 -z-10">
          <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-amber-500/10 blur-[150px] rounded-full"></div>
          <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-cyan-500/10 blur-[150px] rounded-full"></div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <span className="inline-flex items-center gap-2 py-1 px-4 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-sm font-medium mb-6">
              <Sparkles className="w-4 h-4" />
              Voices of Impact
            </span>
            <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-6">
              What People <span className="text-gradient">Say</span>
            </h1>
            <p className="text-lg text-slate-400 max-w-2xl mx-auto">
              Genuine feedback from colleagues, leaders, and collaborators who've experienced 
              the passion, dedication, and impact of working together.
            </p>
          </motion.div>
        </div>
      </section>

      {/* Featured Testimonials + Sentiment Chart Section */}
      <section className="py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">
            {/* Carousel - Left Side */}
            <div className="relative">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeFeatured}
                  initial={{ opacity: 0, x: 50 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -50 }}
                  transition={{ duration: 0.5 }}
                  className="relative"
                >
                  <div className="relative p-8 rounded-3xl bg-gradient-to-br from-amber-500/5 via-slate-900 to-cyan-500/5 border border-amber-500/20 min-h-[320px]">
                    <div className="absolute top-4 left-6 text-6xl text-amber-500/20 font-serif">"</div>
                    <div className="absolute bottom-4 right-6 text-6xl text-cyan-500/20 font-serif rotate-180">"</div>
                    
                    <div className="relative z-10">
                      <div className="flex gap-1 mb-4">
                        {[...Array(5)].map((_, i) => (
                          <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                        ))}
                      </div>
                      
                      <p className="text-base text-slate-200 leading-relaxed mb-6 italic line-clamp-5">
                        {featuredTestimonials[activeFeatured].statement}
                      </p>
                      
                      <div>
                        <p className="text-lg font-bold text-white">
                          {featuredTestimonials[activeFeatured].name}
                        </p>
                        <p className="text-amber-400 text-sm">
                          {featuredTestimonials[activeFeatured].role}
                        </p>
                        <span className="inline-block mt-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-medium">
                          {featuredTestimonials[activeFeatured].highlight}
                        </span>
                      </div>
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>

              {/* Carousel Controls */}
              <div className="flex justify-center gap-4 mt-6">
                <button
                  onClick={prevFeatured}
                  className="p-2 rounded-full bg-slate-800 border border-slate-700 hover:border-amber-500/50 hover:bg-amber-500/10 transition-all group"
                >
                  <ChevronLeft className="w-4 h-4 text-slate-400 group-hover:text-amber-400" />
                </button>
                <div className="flex items-center gap-2">
                  {featuredTestimonials.map((_, i) => (
                    <button
                      key={i}
                      onClick={() => setActiveFeatured(i)}
                      className={`h-2 rounded-full transition-all ${
                        i === activeFeatured 
                          ? 'w-6 bg-amber-400' 
                          : 'w-2 bg-slate-600 hover:bg-slate-500'
                      }`}
                    />
                  ))}
                </div>
                <button
                  onClick={nextFeatured}
                  className="p-2 rounded-full bg-slate-800 border border-slate-700 hover:border-amber-500/50 hover:bg-amber-500/10 transition-all group"
                >
                  <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-amber-400" />
                </button>
              </div>
            </div>

            {/* Sentiment Chart - Right Side */}
            <div className="relative p-6 rounded-3xl bg-slate-900/80 border border-slate-800">
              <h3 className="text-lg font-semibold text-white mb-2 text-center">
                Sentiment Analysis
              </h3>
              <p className="text-sm text-slate-400 text-center mb-4">
                Themes from {allTestimonials.length} testimonials
              </p>
              
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={sentimentData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={4}
                      dataKey="value"
                    >
                      {sentimentData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: '#1e293b', 
                        border: '1px solid #334155',
                        borderRadius: '8px',
                        color: '#f1f5f9'
                      }}
                    />
                    <Legend 
                      verticalAlign="bottom" 
                      height={36}
                      iconType="circle"
                      formatter={(value) => <span className="text-slate-300 text-xs">{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              {/* Stats summary */}
              <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-slate-800">
                <div className="text-center">
                  <p className="text-2xl font-bold text-amber-400">{allTestimonials.length}</p>
                  <p className="text-xs text-slate-500">Total Reviews</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-cyan-400">15+</p>
                  <p className="text-xs text-slate-500">Years Impact</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-purple-400">100%</p>
                  <p className="text-xs text-slate-500">Positive</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* All Testimonials Grid */}
      <section className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              All <span className="text-gradient">Testimonials</span>
            </h2>
            <p className="text-slate-400">
              Testimonials from leadership, peers, and clients.
            </p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {allTestimonials.map((testimonial, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.02 }}
                className="group relative"
              >
                <div className="h-full p-6 rounded-2xl bg-slate-900/80 border border-slate-800 hover:border-cyan-500/30 transition-all duration-300 hover:shadow-lg hover:shadow-cyan-500/5 hover:-translate-y-1">
                  {/* Quote Icon */}
                  <div className="absolute -top-3 -left-3 w-10 h-10 rounded-full bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center shadow-lg">
                    <Quote className="w-5 h-5 text-white" />
                  </div>

                  {/* Category Tag */}
                  <div className="flex justify-end mb-4">
                    <span className="text-xs px-3 py-1 rounded-full bg-slate-800 text-slate-400 group-hover:bg-cyan-500/10 group-hover:text-cyan-400 transition-colors">
                      {testimonial.category}
                    </span>
                  </div>

                  {/* Statement */}
                  <p className="text-slate-300 text-sm leading-relaxed mb-6 line-clamp-6">
                    "{testimonial.statement}"
                  </p>

                  {/* Author */}
                  <div className="pt-4 border-t border-slate-800">
                    <p className="font-semibold text-white group-hover:text-cyan-400 transition-colors">
                      {testimonial.name}
                    </p>
                    <p className="text-sm text-slate-500">
                      {testimonial.role}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Testimonials;
