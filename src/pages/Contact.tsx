import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Mail, Phone, MapPin, Send, CheckCircle2, MessageSquare, Building2, Globe } from 'lucide-react';

const Contact = () => {
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const formData = new FormData(e.currentTarget);
    
    try {
      const response = await fetch('https://formspree.io/f/mvzkjrbn', {
        method: 'POST',
        body: formData,
        headers: {
          'Accept': 'application/json'
        }
      });

      if (response.ok) {
        setSubmitted(true);
      } else {
        const data = await response.json();
        setError(data.error || 'Something went wrong. Please try again.');
      }
    } catch (err) {
      setError('Failed to send message. Please check your connection.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16">
          {/* Contact Info */}
          <div>
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
            >
              <h1 className="text-4xl md:text-5xl font-bold mb-6">Let's Solve Your <br /><span className="text-gradient">Engineering Challenges</span></h1>
              <p className="text-slate-400 text-lg mb-12 leading-relaxed">
                Whether you need a deep-dive combustion analysis, a custom AI model, or specialized training for your team, we're ready to help.
              </p>

              <div className="space-y-8">
                {[
                  { icon: <Mail />, title: "Email Us", detail: "info@proreadyengineer.com", sub: "Response within 24 hours" },
                  { icon: <Phone />, title: "Call Us", detail: "+1 (513) 849-1016", sub: "Mon-Fri, 9am-5pm EST" },
                  { icon: <MapPin />, title: "Office", detail: "9550 Mason Montgomery Rd. #162", sub: "Mason, OH 45040" }
                ].map((item, i) => (
                  <div key={i} className="flex gap-6">
                    <div className="w-12 h-12 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-cyan-400 shrink-0">
                      {item.icon}
                    </div>
                    <div>
                      <h4 className="font-bold text-white">{item.title}</h4>
                      <p className="text-slate-300">{item.detail}</p>
                      <p className="text-xs text-slate-500 mt-1">{item.sub}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-16 p-8 rounded-3xl bg-cyan-500/5 border border-cyan-500/10">
                <h4 className="font-bold mb-4 flex items-center gap-2">
                  <Globe className="w-5 h-5 text-cyan-400" />
                  Global Consulting
                </h4>
                <p className="text-sm text-slate-400 leading-relaxed">
                  We work with clients worldwide, offering both remote analysis and on-site technical support for critical projects.
                </p>
              </div>
            </motion.div>
          </div>

          {/* Contact Form */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            className="relative"
          >
            <div className="absolute inset-0 bg-cyan-500/5 blur-3xl -z-10 rounded-full"></div>
            <div className="bg-slate-900/50 border border-slate-800 p-8 md:p-10 rounded-[2.5rem] backdrop-blur-sm">
              {submitted ? (
                <div className="text-center py-12">
                  <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                    <CheckCircle2 className="w-10 h-10 text-cyan-400" />
                  </div>
                  <h3 className="text-2xl font-bold mb-4">Message Received</h3>
                  <p className="text-slate-400 mb-8">
                    Thank you for reaching out. One of our principal engineers will review your inquiry and contact you shortly.
                  </p>
                  <button 
                    onClick={() => setSubmitted(false)}
                    className="btn-secondary w-full"
                  >
                    Send Another Message
                  </button>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  {error && (
                    <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
                      {error}
                    </div>
                  )}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">Full Name</label>
                      <div className="relative">
                        <input required name="name" type="text" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors" placeholder="John Doe" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">Email Address</label>
                      <input required name="email" type="email" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors" placeholder="john@company.com" />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">Company</label>
                      <div className="relative">
                        <Building2 className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input name="company" type="text" className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-11 pr-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors" placeholder="Engineering Corp" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">Inquiry Type</label>
                      <select name="inquiry_type" className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors appearance-none text-slate-400">
                        <option>Consulting Services</option>
                        <option>Training & Workshops</option>
                        <option>AI & Data Analytics</option>
                        <option>Other</option>
                      </select>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">Project Details</label>
                    <div className="relative">
                      <MessageSquare className="absolute left-4 top-4 w-4 h-4 text-slate-600" />
                      <textarea required name="message" rows={4} className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-11 pr-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors resize-none" placeholder="Tell us about your technical requirements..."></textarea>
                    </div>
                  </div>

                  <button 
                    type="submit" 
                    disabled={loading}
                    className="btn-primary w-full flex items-center justify-center gap-2 py-4 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loading ? 'Sending...' : 'Send Inquiry'} <Send className="w-4 h-4" />
                  </button>
                  
                  <p className="text-[10px] text-slate-600 text-center uppercase tracking-widest">
                    Secure & Confidential Engineering Consultation
                  </p>
                </form>
              )}
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
};

export default Contact;