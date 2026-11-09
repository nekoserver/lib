import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'ops'))
from chat_observer import public_queue_summary
class SummaryTest(unittest.TestCase):
 def test_only_counts_are_public(self):
  result=public_queue_summary({'data':[{'id':'secret-id','input':[{'text':'private draft'}]}],'nextCursor':None})
  self.assertEqual(result,{'available':True,'pending':1,'hasMore':False})
 def test_bad_response_is_unknown_not_empty(self):
  for value in [None,{}, {'data':None}]:self.assertEqual(public_queue_summary(value),{'available':False})
if __name__=='__main__':unittest.main()
