
"""
YAML (IETF network schema) → JSONL (CMDB objects) ETL script
Usage:
	python etl.py <input.yaml> > <output.jsonl>
"""
import sys, yaml, json

def extract_objects(yaml_data):
	# IETF network schema: networks → network → node
	objects = []
	networks = yaml_data.get('ietf-network:networks', {})
	for net in networks.get('network', []):
		network_id = net.get('network-id')
		# network本体
		net_obj = {
			"type": "network",
			"network-id": network_id
		}
		objects.append(net_obj)
		for node in net.get('node', []):
			node_obj = {
				"type": "node",
				"network-id": network_id,
				"node-id": node.get("node-id")
			}
			objects.append(node_obj)
			for tp in node.get('termination-point', []):
				tp_obj = {
					"type": "termination-point",
					"network-id": network_id,
					"node-id": node.get("node-id"),
					"tp-id": tp.get("tp-id")
				}
				# TP属性（例: operational:ipv4）も展開
				for k, v in tp.items():
					if k != "tp-id":
						tp_obj[k] = v
				objects.append(tp_obj)
	return objects

def main():
	if len(sys.argv) < 2:
		print("Usage: python etl.py <input.yaml>", file=sys.stderr)
		sys.exit(1)
	with open(sys.argv[1], 'r', encoding='utf-8') as f:
		yaml_data = yaml.safe_load(f)
	objects = extract_objects(yaml_data)
	for obj in objects:
		print(json.dumps(obj, ensure_ascii=False))

if __name__ == "__main__":
	main()
