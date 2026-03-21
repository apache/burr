import Navbar from "@/components/Navbar";
import Hero from "@/components/Hero";
import CodeTabs from "@/components/CodeTabs";
import Features from "@/components/Features";
import Integrations from "@/components/Integrations";
import Testimonials from "@/components/Testimonials";
import Community from "@/components/Community";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        <Hero />
        <CodeTabs />
        <Features />
        <Integrations />
        <Testimonials />
        <Community />
      </main>
      <Footer />
    </>
  );
}
