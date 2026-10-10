import test from 'node:test';
import assert from 'node:assert/strict';
import { deviceState, transitionTask, metricSeries, chartSegments } from './state.mjs';
test('device interruptions always mark old data stale', () => {
 assert.equal(deviceState(true,true,false).stale,false);
 for (const args of [[false,true,false],[true,false,false],[true,true,true]]) assert.equal(deviceState(...args).stale,true);
});
test('tasks cannot be completed before claiming or reopened once completed', () => {
 assert.equal(transitionTask('pending','complete'),'pending');
 assert.equal(transitionTask('pending','claim'),'claimed');
 assert.equal(transitionTask('claimed','complete'),'completed');
 assert.equal(transitionTask('completed','claim'),'completed');
 assert.equal(transitionTask('deferred','claim'),'claimed');
});
test('missing observations remain a genuine gap in all metrics', () => {
 for(const person of ['mother','father']) for(const metric of ['speed','cadence']) {
 const values=metricSeries(person,metric); assert.equal(values[3],null);
 const segments=chartSegments(values); assert.equal(segments.length,2);
 assert.deepEqual(segments.map(s=>s.map(p=>p.index)),[[0,1,2],[4,5,6]]);
 }
 assert.notDeepEqual(metricSeries('mother','speed'),metricSeries('father','speed'));
});
