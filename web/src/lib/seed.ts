// Static demo content the UI needs before the API answers: port location and sample texts
// (same texts as smartlading.demo.SAMPLE_NEWS).

export const PORT = { name: 'Port of Long Beach', city: 'Long Beach, CA', lat: 33.754, lng: -118.216 }

export const sampleNews = [
  {
    title: 'USTR Section 301 update',
    source_type: 'tariff' as const,
    text: 'WASHINGTON — The Office of the U.S. Trade Representative said Tuesday it will raise the additional Section 301 duty on wooden bedroom furniture under HTS 9403.50 to 35% effective December 1. Officials said a final decision depends on the outcome of the comment period, which several trade groups expect to pass largely unchanged. Seating and lighting products are not affected.',
  },
  {
    title: 'Shenzhen factory slowdown',
    source_type: 'supplier_news' as const,
    text: 'Several furniture makers in Shenzhen, including Everbright Woodcraft, warned buyers that rolling power cuts will add about 14 days to production schedules through the end of the quarter. Everbright also told customers it will raise the deposit it requires on new orders to 40%.',
  },
  {
    title: 'Port congestion easing',
    source_type: 'other' as const,
    text: 'Container dwell times at the ports of Los Angeles and Long Beach fell for a third straight month, according to the Pacific Merchant Shipping Association. Analysts described conditions as broadly normal heading into the holiday season.',
  },
]
