console.log(JSON.stringify({valid: false, errors: [{path: '/beats/1/from', rule: 'S09', message: 'shown frames exceed loop length'}], warnings: [{path: '/beats/2', rule: 'S11', message: 'aspect drift'}], schemaSha256: 'stub'}));
process.exit(1);
