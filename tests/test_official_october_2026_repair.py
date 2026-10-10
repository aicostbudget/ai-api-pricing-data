import copy, json, unittest
from pathlib import Path
from scripts.pricing_contract import normalize_canonical_price_records, select_price_record, validate_model_price_records, PricingContractError
from scripts.generate_price_change_events import load_events, generate_events
from scripts.generate_website_projection_v2 import validate_price_records
from scripts.lifecycle_authority import validate_unresolved_conflict

ROOT=Path(__file__).resolve().parents[1]
class OctoberOfficialRepairTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.models={m['model_id']:m for m in json.loads((ROOT/'data/canonical/models.json').read_text(encoding='utf-8'))}
  cls.projection={m['id']:m for m in json.loads((ROOT/'data/pricing-v2-preview/generated/model-pricing.v2.json').read_text(encoding='utf-8'))['models']}
  cls.events=load_events()
 def normalized(self,id):
  m=self.models[id]; return normalize_canonical_price_records(m['provider_id']+'/'+id,m['price_records'],lambda x:x)
 def amounts(self,id,mode,context='short'):
  r=next(r for r in self.models[id]['price_records'] if r['processing_mode']==mode and r['context_class']==context)
  return {(c['component'],c['modality']):c['amount'] for c in r['charges']}
 def test_haiku_identity(self):
  m=self.models['claude-haiku-5-5']; self.assertEqual((m['released_at'],m['status'],m['context_window_tokens'],m['max_output_tokens']),('2026-10-07','active',1000000,128000))
 def test_haiku_whole_request_boundary(self):
  records=self.normalized('claude-haiku-5-5')
  for mode in ['standard','batch']:
   for tokens,context in [(99999,'short'),(100000,'short'),(100001,'long'),(1000000,'long')]:
    r=select_price_record(records,processing_mode=mode,prompt_tokens=tokens,at='2026-10-09'); self.assertEqual(r['contextClass'],context)
  for r in records: self.assertTrue(r['tierSelection']['cachedPromptTokensIncluded']); self.assertTrue(r['tierSelection']['wholeRequestPricing'])
 def test_haiku_components_and_batch(self):
  for context,expected in [('short',['0.1','0.01','0.125','0.2','0.5']),('long',['0.5','0.05','0.625','1','2.5'])]:
   values=self.amounts('claude-haiku-5-5','standard',context)
   self.assertEqual([values[(c,'text')] for c in ['input','cache_read','cache_write_5m','cache_write_1h','output']],expected)
  self.assertEqual(self.amounts('claude-haiku-5-5','batch'),{('input','text'):'0.05',('output','text'):'0.25'})
  self.assertEqual(self.amounts('claude-haiku-5-5','batch','long'),{('input','text'):'0.25',('output','text'):'1.25'})
 def test_sonnet_real_component_delta(self):
  m=self.models['claude-sonnet-5-5']; self.assertEqual(m['pricing']['cached_input'],0.1)
  self.assertEqual(self.amounts('claude-sonnet-5-5','standard'),{('input','text'):'2',('cache_read','text'):'0.1',('cache_write_5m','text'):'2.5',('cache_write_1h','text'):'4',('output','text'):'10'})
  e=next(e for e in self.events if e['model_id']==m['model_id'] and e['change_type']=='component_price_update')
  self.assertEqual((e['old_prices']['cached_input'],e['new_prices']['cached_input'],e['effective_from']),(0.2,0.1,'2026-10-07'))
  self.assertEqual([(c['component'],c['old_amount'],c['new_amount']) for c in e['component_changes']],[('cache_read','0.2','0.1')])
 def test_nano_modality_prices(self):
  for mode,ip,op,img in [('standard','1.5','7.5','30'),('batch','0.75','3.75','15')]:
   self.assertEqual(self.amounts('gemini-nano-banana-2.1',mode),{('input',m):ip for m in ['text','image','video']} | {('output','text'):op,('output','image'):img})
  m=self.models['gemini-nano-banana-2.1']; self.assertIsNone(m['pricing']['cached_input']); self.assertEqual(len(m['price_records']),2); self.assertEqual(m['max_output_tokens'],32768)
 def test_mistral_list_and_sale_survive(self):
  m=self.models['mistral-large-4']; self.assertEqual((m['status'],m['release_stage'],m['context_window_tokens']),('preview','preview',1000000))
  r=m['price_records'][0]; self.assertEqual([c['amount'] for c in r['charges']],['0.68','0.07','2.09']); self.assertEqual([c['amount'] for c in r['promotion']['list_charges']],['1.36','0.14','4.18']); self.assertIsNone(r['effective_until']); self.assertNotIn('2026-10-20',json.dumps(m))
  row=self.projection[m['model_id']]; p=row['priceRecords'][0]['promotion']; self.assertEqual(p['priceBasis'],'promotional'); self.assertEqual(p['durationText'],'2 weeks'); self.assertEqual([c['amount'] for c in p['listCharges']],['1.36','0.14','4.18'])
  self.assertTrue(all(c['condition']['promotion']==p for c in row['pricingComponents']))
 def test_promotion_is_an_observation_not_an_undated_future_rate(self):
  records=self.normalized('mistral-large-4')
  self.assertEqual(select_price_record(records,processing_mode='standard',prompt_tokens=100,at='2026-10-09')['selectionStatus'],'available')
  self.assertNotEqual(select_price_record(records,processing_mode='standard',prompt_tokens=100,at='2026-10-21')['selectionStatus'],'available')
 def test_hf_retains_list_price_and_promotion(self):
  rows=json.loads((ROOT/'huggingface/prices.json').read_text(encoding='utf-8'))['records']
  record=next(r for r in rows if r['model_id']=='mistral-large-4')
  p=record['pricing_components'][0]['condition']['promotion']
  self.assertEqual([c['amount'] for c in p['list_charges']],['1.36','0.14','4.18'])
  self.assertEqual(p['price_basis'],'promotional')
  self.assertIsNone(record['pricing_components'][0]['condition']['effective_until'])
 def test_invalid_sale_does_not_pass(self):
  m=copy.deepcopy(self.models['mistral-large-4']); m['price_records'][0]['promotion']['list_charges'][0]['amount']='0.68'
  with self.assertRaises(PricingContractError): validate_model_price_records(m)
 def test_unresolved_conflict_blocks_certain_facts(self):
  m=self.models['gemini-2.5-flash-image']; validate_unresolved_conflict(m)
  row=self.projection[m['model_id']]; self.assertFalse(row['defaultSafe']); self.assertEqual(row['lifecycleStatus'],'unknown'); self.assertIsNone(row['retirementDate']); self.assertIsNone(row['verifiedAt'])
  for status in ['active','retired']:
   bad=copy.deepcopy(m); bad['status']=status
   with self.assertRaises(ValueError): validate_unresolved_conflict(bad)
 def test_events_are_additions_not_cross_model_cuts(self):
  for id in ['claude-haiku-5-5','gemini-nano-banana-2.1','mistral-large-4']:
   events=[e for e in self.events if e['model_id']==id]; self.assertEqual(len(events),1); self.assertEqual(events[0]['change_type'],'model_added'); self.assertNotIn('predecessor_model_id',events[0])
 def test_structured_projection_keeps_modalities_and_tiers(self):
  h=self.projection['claude-haiku-5-5']; self.assertEqual(len(h['pricingTiers']),2); self.assertEqual(len(h['pricingComponents']),14)
  n=self.projection['gemini-nano-banana-2.1']; self.assertEqual({(c['condition']['processingMode'],c['modality'],c['amount']) for c in n['pricingComponents'] if c['component']=='output'},{('standard','text','7.5'),('standard','image','30'),('batch','text','3.75'),('batch','image','15')})
 def test_rerun_no_unresolved_lifecycle_event(self):
  events=generate_events(ROOT/'data/snapshots/2026-10-08/prices.json',ROOT/'data/snapshots/2026-10-09/prices.json',model_ids={'gemini-2.5-flash-image'})
  self.assertEqual(events,[])
if __name__=='__main__': unittest.main()
